"""
网络性能测试模块，封装了在 Docker 容器间执行 Ping 和 Iperf3 的逻辑。
"""

import json
import re
import subprocess
import time


def _run(args, timeout):
    """
    [内部函数] 执行带超时的 Shell 命令并捕获输出。
    """
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def ping_test(target, attempts=2):
    """
    执行 Ping 测试，返回平均 RTT 和实际丢包率。
    默认发送 1000 个包，发包间隔 0.05 秒，总耗时约 50 秒。
    
    :param target: 目标容器名称或 IP 地址
    :param attempts: 失败重试次数
    :return: (avg_rtt, real_loss)
    """
    print(f" 正在执行 Ping 测试 (目标: {target}，约需 50 秒)...")
    
    for attempt in range(1, attempts + 1):
        try:
            # 核心参数: -c 1000 (发包量), -i 0.05 (发包间隔), -W 2 (超时时间)
            # 总耗时约 50 秒，subprocess 超时设为 120 秒留出余量
            result = _run(
                ["docker", "exec", "test_a", "ping", "-c", "10000", "-i", "0.01", "-W", "2", target], 
                timeout=2000
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
                
        print(f" Ping 测试第 {attempt}/{attempts} 次失败，准备重试...")
        time.sleep(1)
        
    print(" Ping 测试最终失败，返回默认值 (0.0 ms, 100.0%)。")
    return 0.0, 100.0


def _server_name(target):
    """
    [内部函数] 将目标 IP 或名称映射为底层服务端容器名。
    链式拓扑中，172.22.0.3 对应的就是 test_c 容器。
    """
    return "test_c" if target in ("test_c", "172.22.0.3") else target


def _restart_iperf_server(target):
    """
    [内部函数] 重启目标容器上的 iperf3 服务端进程，防止端口被占用或假死。
    """
    server = _server_name(target)
    
    # 强杀旧进程 (忽略报错)
    _run(["docker", "exec", server, "pkill", "-9", "iperf3"], timeout=10)
    
    # 后台启动新进程 (单次模式 -1)，不捕获输出以防阻塞
    subprocess.run(
        ["docker", "exec", "-d", server, "iperf3", "-s", "-1"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)


def iperf_test(target, attempts=2):
    """
    执行 Iperf3 吞吐量测试，解析 JSON 结果并返回带宽测量值 (Mbps)。
    
    :param target: 目标容器名称或 IP 地址
    :param attempts: 失败重试次数
    :return: throughput (Mbps)
    """
    print(f" 正在执行 Iperf3 吞吐量测试 (目标: {target}，约需 15 秒)...")
    
    for attempt in range(1, attempts + 1):
        _restart_iperf_server(target)
        
        try:
            # -t 15: 测试 15 秒
            # --omit 3: 忽略前 3 秒的 TCP 慢启动预热数据，使结果更准确
            result = _run([
                "docker", "exec", "test_a", "iperf3", "-c", target,
                "-t", "15", "--omit", "3", "--json",
            ], timeout=35)
            
            payload = json.loads(result.stdout)
            bits_per_second = payload["end"]["sum_received"]["bits_per_second"]
            throughput = bits_per_second / 1_000_000
            
            if result.returncode == 0 and throughput > 0:
                throughput_rounded = round(throughput, 3)
                print(f"  └─ Iperf3 测量完成: 吞吐量 = {throughput_rounded} Mbps")
                return throughput_rounded
                
        except subprocess.TimeoutExpired:
            print(f" Iperf3 测试执行超时 (第 {attempt}/{attempts} 次)。")
        except (json.JSONDecodeError, KeyError, TypeError):
            print(f" Iperf3 结果解析失败 (第 {attempt}/{attempts} 次)，可能网络完全断开导致无法生成 JSON。")
            
        time.sleep(2)
        
    print(" Iperf3 测试最终失败，返回默认吞吐量 (0.0 Mbps)。")
    return 0.0
