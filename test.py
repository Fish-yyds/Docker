"""容器间 Ping 连通性、时延、丢包率与 Iperf3 吞吐量测量。"""

import json
import math
import os
import re
import subprocess
import time

# 目标数据地址与原生 Docker 服务端容器的对应关系。
IPERF_SERVERS = {
    "172.22.0.3": "test_c",
    "172.25.0.3": "test_b",
    "172.26.0.3": "test_c",
    "172.27.0.3": "test_c",
}


def _run(args, timeout):
    """执行 args 命令；timeout 为最大等待秒数，返回命令执行结果。"""
    return subprocess.run(
        args, check=False, capture_output=True, text=True, timeout=timeout
    )


def _detail(result):
    """从命令结果中提取错误信息，优先返回标准错误。"""
    return result.stderr.strip() or result.stdout.strip() or "无错误输出"


def _server_name(target, source):
    """根据目标地址和源容器判断 Iperf3 服务端容器名称。"""
    server = IPERF_SERVERS.get(target, target)

    # Containerlab 与 Docker 使用相同地址，但容器名称前缀不同。
    if source.startswith("clab-mesh-") and server.startswith("test_"):
        return f"clab-mesh-{server}"
    return server


def _restart_iperf_server(target, source):
    """在 target 对应容器中重启一次性 Iperf3 服务，并返回容器名称。"""
    server = _server_name(target, source)

    # 清理残留进程，避免 5201 端口被旧服务占用。
    _run(["docker", "exec", server, "pkill", "-9", "iperf3"], 10)
    started = _run(
        ["docker", "exec", "-d", server, "iperf3", "-s", "-1"], 10
    )
    if started.returncode:
        raise RuntimeError(f"Iperf3 服务端启动失败：{server}\n{_detail(started)}")

    # 等待服务启动，并确认进程仍处于运行状态。
    time.sleep(1)
    if _run(["docker", "exec", server, "pgrep", "-x", "iperf3"], 5).returncode:
        raise RuntimeError(f"Iperf3 服务端未保持运行：{server}")
    return server


def ping_test(target, source="test_a", attempts=2):
    """从 source Ping target；attempts 为重试次数，返回平均 RTT 和丢包率。"""
    print(f"[测量] Ping：{source} -> {target}")

    # 先发送 5 个包快速检查连通性，避免不可达时执行长时间测量。
    probe = _run(
        ["docker", "exec", source, "ping", "-n", "-c", "5", "-i", "0.2", "-W", "1", target],
        8,
    )
    if probe.returncode:
        print(f"[失败] 快速连通性检查未通过，本轮不执行长测量。\n{_detail(probe)}")
        return 0.0, 100.0

    # 自动测试可通过环境变量覆盖默认包数量和发包间隔。
    count = max(10, int(os.getenv("NETWORK_SIM_PING_COUNT", "500")))
    interval = max(0.01, float(os.getenv("NETWORK_SIM_PING_INTERVAL", "0.02")))
    deadline = math.ceil(count * interval + 10)
    command = [
        "docker", "exec", source, "ping", "-n", "-c", str(count),
        "-i", str(interval), "-W", "2", "-w", str(deadline), target,
    ]

    for attempt in range(1, attempts + 1):
        try:
            result = _run(command, deadline + 5)
        except subprocess.TimeoutExpired:
            print(f"[重试] Ping 超时：{attempt}/{attempts}")
            continue

        # 从 Ping 输出中解析丢包率和 min/avg/max/mdev 的平均 RTT。
        loss = re.search(r"([\d.]+)% packet loss", result.stdout)
        if loss:
            rtt = re.search(r"=\s*[\d.]+/([\d.]+)/[\d.]+/[\d.]+", result.stdout)
            values = (float(rtt.group(1)) if rtt else 0.0, float(loss.group(1)))
            print(f"[完成] Ping：RTT={values[0]}ms，丢包率={values[1]}%")
            return values

        print(f"[重试] Ping 输出无法解析：{attempt}/{attempts}")

    print("[失败] Ping 未获得有效结果。")
    return 0.0, 100.0


def iperf_test(target, source="test_a", attempts=2):
    """从 source 测量 target 的 TCP 接收吞吐量；失败返回 0 Mbps。"""
    print(f"[测量] Iperf3：{source} -> {target}")

    # 测试 15 秒并忽略前 3 秒预热数据，以 JSON 格式返回结果。
    command = [
        "docker", "exec", source, "iperf3", "-c", target,
        "-t", "15", "--omit", "3", "--json",
    ]

    for attempt in range(1, attempts + 1):
        # 每次测试前重新启动一次性服务，避免残留连接影响结果。
        server = _restart_iperf_server(target, source)
        try:
            result = _run(command, 35)
        except subprocess.TimeoutExpired:
            print(f"[重试] Iperf3 超时：{attempt}/{attempts}，服务端={server}")
            continue

        if result.returncode:
            print(f"[重试] Iperf3 失败：{attempt}/{attempts}\n{_detail(result)}")
            continue

        # 使用接收端统计值，避免发送端缓存造成吞吐量虚高。
        try:
            payload = json.loads(result.stdout)
            throughput = payload["end"]["sum_received"]["bits_per_second"] / 1_000_000
        except (json.JSONDecodeError, KeyError, TypeError):
            print(f"[重试] Iperf3 JSON 无有效接收结果：{attempt}/{attempts}")
            continue

        if throughput > 0:
            value = round(throughput, 3)
            print(f"[完成] Iperf3：吞吐量={value}Mbps，服务端={server}")
            return value

    print("[失败] Iperf3 未获得有效吞吐量。")
    return 0.0