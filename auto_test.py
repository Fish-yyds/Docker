"""
通信系统仿真平台 - 自动化批量测试逻辑模块
提供星型、链式和网状拓扑的全矩阵测试函数，供其他模块调用，也支持直接运行。
"""

import os
import time
from datetime import datetime

from damage import set_damage
from database import result_path, save_result
from test import iperf_test, ping_test

# ==================================
# 自动化测试参数矩阵配置
# ==================================
BASELINE = {"delay": 0, "jitter": 0, "loss": 0, "bandwidth": 1000}
DELAY_VALUES = (10, 50, 100, 200)
LOSS_VALUES = (1, 3, 5, 10)
GRID_DELAYS = (0, 10, 50, 100, 200)
GRID_LOSSES = (0, 1, 3, 5, 10)
REPEATS = max(1, int(os.getenv("NETWORK_SIM_REPEATS", "1")))
CHAIN_SPLIT_RATIO = 0.3


def experiment_matrix():
    """生成并去重测试参数矩阵"""
    candidates = [BASELINE]
    candidates += [{**BASELINE, "delay": value} for value in DELAY_VALUES]
    candidates += [{**BASELINE, "loss": value} for value in LOSS_VALUES]
    candidates += [
        {**BASELINE, "delay": delay, "loss": loss}
        for delay in GRID_DELAYS
        for loss in GRID_LOSSES
    ]
    
    unique_trials = []
    for trial in candidates:
        if trial not in unique_trials:
            unique_trials.append(trial)
    return unique_trials


def archive_history_data(topology):
    """备份指定拓扑的历史数据"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = result_path(topology)
    if path.exists():
        backup = path.with_name(f"{path.stem}_{stamp}.bak.txt")
        path.replace(backup)
        print(f"\n[成功] 旧数据已安全备份至: {backup}")


def _auto_measure(target, source="test_a", attempts=3):
    """内置重试机制的自动化测量函数，支持指定发包源"""
    for attempt in range(1, attempts + 1):
        avg_rtt, measured_loss = ping_test(target, source=source)
        throughput = iperf_test(target, source=source)
        
        if throughput > 0:
            return avg_rtt, measured_loss, throughput
            
        print(f" [警告] {target} 完整测量第 {attempt}/{attempts} 次失败 (吞吐量为0)，准备重试...")
        time.sleep(2)
        
    return None


def run_star_auto_link(target, interface):
    """针对星型拓扑的单一链路执行全矩阵测试"""
    trials = experiment_matrix()
    total_trials = len(trials)
    
    for repeat in range(1, REPEATS + 1):
        for index, trial in enumerate(trials, start=1):
            print(f"\n[{'='*40}]")
            print(f" [自动测试 | 星型 {target}] 循环 {repeat}/{REPEATS} | 测试组 {index}/{total_trials}")
            print(f"[{'='*40}]")
            
            set_damage("test_a", interface, **trial)
            measurement = _auto_measure(target)
            
            if measurement is None:
                print(f" [跳过] {target} 参数组 {trial}: 未获取到有效数据")
                continue
                
            avg_rtt, measured_loss, throughput = measurement
            save_result([
                target, trial["delay"], trial["jitter"], trial["loss"],
                trial["bandwidth"], avg_rtt, measured_loss, throughput,
            ], "star")
            
            time.sleep(1)


def run_chain_auto_tests():
    """针对链式拓扑执行全矩阵测试 (含非对称拆分)"""
    trials = experiment_matrix()
    total_trials = len(trials)
    
    for repeat in range(1, REPEATS + 1):
        for index, trial in enumerate(trials, start=1):
            print(f"\n[{'='*40}]")
            print(f" [自动测试 | 链式端到端] 循环 {repeat}/{REPEATS} | 测试组 {index}/{total_trials}")
            print(f"[{'='*40}]")
            
            ab_delay = round(trial["delay"] * CHAIN_SPLIT_RATIO, 2)
            bc_delay = round(trial["delay"] - ab_delay, 2)
            ab_loss = round(trial["loss"] * CHAIN_SPLIT_RATIO, 2)
            bc_loss = round(trial["loss"] - ab_loss, 2)
            
            set_damage("test_a", "eth0", delay=ab_delay, jitter=trial["jitter"], loss=ab_loss, bandwidth=trial["bandwidth"])
            set_damage("test_b", "eth1", delay=bc_delay, jitter=trial["jitter"], loss=bc_loss, bandwidth=0)
            
            measurement = _auto_measure("172.22.0.3")
            if measurement is None:
                print(f" [跳过] 链式参数组 {trial}: 未获取到有效数据")
                continue
                
            avg_rtt, measured_loss, throughput = measurement
            
            save_result([
                "test_a-->test_b-->test_c",
                {"AB_delay": ab_delay, "AB_jitter": trial["jitter"], "AB_loss": ab_loss, "AB_bandwidth": trial["bandwidth"]},
                {"BC_delay": bc_delay, "BC_jitter": trial["jitter"], "BC_loss": bc_loss, "BC_bandwidth": 0},
                avg_rtt, measured_loss, throughput,
            ], "chain")
            
            time.sleep(1)


def run_mesh_auto_tests():
    """针对网状拓扑的三条互联链路分别执行全矩阵测试"""
    trials = experiment_matrix()
    total_trials = len(trials)
    
    mesh_links = [
        ("test_a<-->test_b", "test_a", "eth0", "172.25.0.3"),
        ("test_b<-->test_c", "test_b", "eth1", "172.26.0.3"),
        ("test_a<-->test_c", "test_a", "eth1", "172.27.0.3") 
    ]
    
    for link_desc, sender, interface, target_ip in mesh_links:
        for repeat in range(1, REPEATS + 1):
            for index, trial in enumerate(trials, start=1):
                print(f"\n[{'='*40}]")
                print(f" [自动测试 | 网状 {link_desc}] 循环 {repeat}/{REPEATS} | 测试组 {index}/{total_trials}")
                print(f"[{'='*40}]")
                
                set_damage(sender, interface, **trial)
                measurement = _auto_measure(target_ip, source=sender)
                
                if measurement is None:
                    print(f" [跳过] {link_desc} 参数组 {trial}: 未获取到有效数据")
                    continue
                    
                avg_rtt, measured_loss, throughput = measurement
                save_result([
                    link_desc, trial["delay"], trial["jitter"], trial["loss"],
                    trial["bandwidth"], avg_rtt, measured_loss, throughput,
                ], "mesh")
                
                time.sleep(1)


if __name__ == "__main__":
    from topology import create_topology
    from plot import generate_plot

    print("\n [开始] 准备顺序执行所有拓扑的自动化测试 (星型 -> 链式 -> 网状)...\n")

    # ==========================
    # 1. 星型拓扑测试
    # ==========================
    print("="*40)
    print(" [阶段 1/3] 开始执行 星型拓扑 (Star) 自动化测试")
    print("="*40)
    create_topology("star")
    archive_history_data("star")
    run_star_auto_link("test_b", "eth0")
    run_star_auto_link("test_c", "eth1")
    print("\n [处理中] 正在生成星型拓扑图表...")
    generate_plot("star")

    # ==========================
    # 2. 链式拓扑测试
    # ==========================
    print("\n" + "="*40)
    print(" [阶段 2/3] 开始执行 链式拓扑 (Chain) 自动化测试")
    print("="*40)
    create_topology("chain")
    archive_history_data("chain")
    run_chain_auto_tests()
    print("\n [处理中] 正在生成链式拓扑图表...")
    generate_plot("chain")

    # ==========================
    # 3. 网状拓扑测试
    # ==========================
    print("\n" + "="*40)
    print(" [阶段 3/3] 开始执行 网状拓扑 (Mesh) 自动化测试")
    print("="*40)
    create_topology("mesh")
    archive_history_data("mesh")
    run_mesh_auto_tests()
    print("\n [处理中] 正在生成网状拓扑图表...")
    generate_plot("mesh")

    print("\n [成功] 所有拓扑的自动化测试与图表生成已全部完成！")
