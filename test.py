"""
网络性能测试模块，封装了在 Docker 容器间执行 Ping 和 Iperf3 的逻辑。
"""

import json
import math
import os
import re
import subprocess
import time


def _run(args, timeout):
    """
    [内部函数] 执行带超时的 Shell 命令并捕获输出。
    """
    try:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 docker 命令，请先启动 Docker 环境。") from exc


def _quick_ping(target, source):
    """用少量报文快速排除容器、路由或 Docker 环境故障。"""
    result = _run(
        ["docker", "exec", source, "ping", "-n", "-c", "5", "-i", "0.2", "-W", "1", target],
        timeout=8,
    )
    return result.returncode == 0, result


def _server_name(target):
    """
    [内部函数] 将目标 IP 或名称映射为底层服务端容器名。
    精准匹配星型、链式以及网状拓扑的所有可能目标 IP。
    """
    ip_map = {
        "172.22.0.3": "test_c",  # 链式拓扑 test_c IP
        "172.25.0.3": "test_b",  # 网状拓扑 net_mesh_ab 中的 test_b IP
        "172.26.0.3": "test_c",  # 网状拓扑 net_mesh_bc 中的 test_c IP
        "172.27.0.2": "test_c",  # 网状拓扑 net_mesh_ac 中的 test_c IP
        "172.27.0.3": "test_c",
    }
    return ip_map.get(target, target)


def _restart_iperf_server(target):
    """
    [内部函数] 重启目标容器上的 iperf3 服务端进程，防止端口被占用或假死。
    """
    server = _server_name(target)
    
    # 强杀旧进程 (忽略报错)
    _run(["docker", "exec", server, "pkill", "-9", "iperf3"], timeout=10)
    
    # 后台启动新进程 (单次模式 -1)，不捕获输出以防阻塞
    result = subprocess.run(
        ["docker", "exec", "-d", server, "iperf3", "-s", "-1"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(f"无法在容器 {server} 中启动 iperf3 服务端。")
    time.sleep(1)


def ping_test(target, source="test_a", attempts=2):
    """
    执行 Ping 测试，返回平均 RTT 和实际丢包率。
    
    :param target: 目标容器名称或 IP 地址
    :param source: 发起 Ping 的源容器名称，默认 test_a
    :param attempts: 失败重试次数
    :return: (avg_rtt, real_loss)
    """
    print(f" [处理中] 正在执行 Ping 测试 (源: {source} -> 目标: {target})...")

    reachable, probe = _quick_ping(target, source)
    if not reachable:
        detail = probe.stderr.strip() or probe.stdout.strip() or "无输出"
        print(f" [失败] 快速连通性预检未通过，跳过长时间测量:\n{detail}")
        return 0.0, 100.0

    packet_count = max(10, int(os.getenv("NETWORK_SIM_PING_COUNT", "500")))
    interval = max(0.01, float(os.getenv("NETWORK_SIM_PING_INTERVAL", "0.02")))
    deadline = math.ceil(packet_count * interval + 10)
    
    for attempt in range(1, attempts + 1):
        try:
            result = _run(
                [
                    "docker", "exec", source, "ping", "-n", "-c", str(packet_count),
                    "-i", str(interval), "-W", "2", "-w", str(deadline), target,
                ],
                timeout=deadline + 5,
            )
        except subprocess.TimeoutExpired:
            result = None
            
        if result and result.stdout:
            # 使用正则精准提取丢包率和平均 RTT
            loss_match = re.search(r"([\d.]+)% packet loss", result.stdout)
            rtt_match = re.search(r"=\s*[\d.]+/([\d.]+)/[\d.]+/[\d.]+", result.stdout)
            
            if loss_match:
                loss = float(loss_match.group(1))
                rtt = float(rtt_match.group(1)) if rtt_match else 0.0
                print(f"  └─ Ping 测量完成: RTT = {rtt} ms, 丢包率 = {loss}%")
                return rtt, loss
                
        print(f" [警告] Ping 测试第 {attempt}/{attempts} 次失败，准备重试...")
        time.sleep(1)
        
    print(" [失败] Ping 测试最终失败，返回默认值 (0.0 ms, 100.0%)。")
    return 0.0, 100.0


def iperf_test(target, source="test_a", attempts=2):
    """
    执行 Iperf3 吞吐量测试，解析 JSON 结果并返回带宽测量值 (Mbps)。
    
    :param target: 目标容器名称或 IP 地址
    :param source: 发起 Iperf3 的源容器名称，默认 test_a
    :param attempts: 失败重试次数
    :return: throughput (Mbps)
    """
    print(f" [处理中] 正在执行 Iperf3 吞吐量测试 (源: {source} -> 目标: {target})...")
    
    for attempt in range(1, attempts + 1):
        _restart_iperf_server(target)
        
        try:
            result = _run([
                "docker", "exec", source, "iperf3", "-c", target,
                "-t", "15", "--omit", "3", "--json",
            ], timeout=35)
            
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "无输出"
                print(f" [警告] Iperf3 客户端失败 (第 {attempt}/{attempts} 次): {detail}")
                time.sleep(2)
                continue

            payload = json.loads(result.stdout)
            if payload.get("error"):
                raise KeyError(payload["error"])
            bits_per_second = payload["end"]["sum_received"]["bits_per_second"]
            throughput = bits_per_second / 1_000_000
            
            if throughput > 0:
                throughput_rounded = round(throughput, 3)
                print(f"  └─ Iperf3 测量完成: 吞吐量 = {throughput_rounded} Mbps")
                return throughput_rounded
                
        except subprocess.TimeoutExpired:
            print(f" [警告] Iperf3 测试执行超时 (第 {attempt}/{attempts} 次)。")
        except (json.JSONDecodeError, KeyError, TypeError):
            print(f" [警告] Iperf3 结果解析失败 (第 {attempt}/{attempts} 次)，可能网络断开未生成 JSON。")
            
        time.sleep(2)
        
    print(" [失败] Iperf3 测试最终失败，返回默认吞吐量 (0.0 Mbps)。")
    return 0.0

