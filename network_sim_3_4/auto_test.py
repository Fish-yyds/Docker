"""
通信系统仿真平台 - 自动化批量测试脚本
自动执行星型和链式拓扑的损伤矩阵测试，并生成数据与可视化图表。
"""

import os
import time
from datetime import datetime

from damage import set_damage
from database import result_path, save_result
from plot import generate_plot
from test import iperf_test, ping_test
from topology import create_topology

# ==================================
# 自动化测试参数矩阵配置
# ==================================

# 基准网络参数
BASELINE = {"delay": 0, "jitter": 0, "loss": 0, "bandwidth": 1000}

# 单因素测试参数 (严格对应任务书数据)
DELAY_VALUES = (10, 50, 100, 200)
LOSS_VALUES = (1, 3, 5, 10)

# 综合损伤实验网格 (包含 0 作为交叉基准点)
GRID_DELAYS = (0, 10, 50, 100, 200)
GRID_LOSSES = (0, 1, 3, 5, 10)

# 测试循环重复次数
REPEATS = max(1, int(os.getenv("NETWORK_SIM_REPEATS", "1")))

# 链式拓扑损伤拆分比例 (第一段 A->B 分配 30%，第二段 B->C 分配 70%)
CHAIN_SPLIT_RATIO = 0.3


def experiment_matrix():
    """
    生成并去重测试参数矩阵（包含单因素测试与综合交叉测试）。
    """
    candidates = [BASELINE]
    candidates += [{**BASELINE, "delay": value} for value in DELAY_VALUES]
    candidates += [{**BASELINE, "loss": value} for value in LOSS_VALUES]
    candidates += [
        {**BASELINE, "delay": delay, "loss": loss}
        for delay in GRID_DELAYS
        for loss in GRID_LOSSES
    ]
    
    # 保持原顺序去重
    unique_trials = []
    for trial in candidates:
        if trial not in unique_trials:
            unique_trials.append(trial)
    return unique_trials


def archive_history_data():
    """
    备份旧的历史测试数据，确保本次运行的数据纯净度。
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for topology in ("star", "chain"):
        path = result_path(topology)
        if path.exists():
            backup = path.with_name(f"{path.stem}_{stamp}.bak.txt")
            path.replace(backup)
            print(f" 旧数据已安全备份至: {backup}")


def _measure(target, attempts=3):
    """
    [内部辅助函数] 统一执行 Ping 和 Iperf 测试，内置失败重试机制，屏蔽无效数据。
    """
    for attempt in range(1, attempts + 1):
        avg_rtt, measured_loss = ping_test(target)
        throughput = iperf_test(target)
        
        # 吞吐量大于 0 视为有效测试
        if throughput > 0:
            return avg_rtt, measured_loss, throughput
            
        print(f" {target} 完整测量第 {attempt}/{attempts} 次失败 (吞吐量为0)，准备重试...")
        time.sleep(2)
        
    return None


def _run_star_link(target, interface):
    """
    [内部辅助函数] 遍历参数矩阵，针对星型拓扑的单一链路执行自动化测试。
    """
    trials = experiment_matrix()
    total_trials = len(trials)
    
    for repeat in range(1, REPEATS + 1):
        for index, trial in enumerate(trials, start=1):
            print(f"\n[{'='*40}]")
            print(f" [星型 {target}] 循环 {repeat}/{REPEATS} | 测试组 {index}/{total_trials}")
            print(f"[{'='*40}]")
            
            # 设置损伤
            set_damage("test_a", interface, **trial)
            
            # 测量并保存
            measurement = _measure(target)
            if measurement is None:
                print(f" 跳过 {target} 参数组 {trial}: 未获取到有效数据")
                continue
                
            avg_rtt, measured_loss, throughput = measurement
            save_result([
                target, trial["delay"], trial["jitter"], trial["loss"],
                trial["bandwidth"], avg_rtt, measured_loss, throughput,
            ], "star")
            
            time.sleep(1)


def run_auto_star():
    """自动化执行星型拓扑测试。"""
    create_topology("star")
    _run_star_link("test_b", "eth0")
    _run_star_link("test_c", "eth1")
    print("\n 正在生成星型拓扑图表...")
    generate_plot("star")


def run_auto_chain():
    """自动化执行链式拓扑测试，并包含非对称损伤拆分验证。"""
    create_topology("chain")
    trials = experiment_matrix()
    total_trials = len(trials)
    
    for repeat in range(1, REPEATS + 1):
        for index, trial in enumerate(trials, start=1):
            print(f"\n[{'='*40}]")
            print(f" [链式端到端] 循环 {repeat}/{REPEATS} | 测试组 {index}/{total_trials}")
            print(f"[{'='*40}]")
            
            # -----------------------------------------------------
            # 【非对称拆分算法】
            # 使用减法计算第二段链路，彻底避免浮点数精度问题，保证和为目标值
            # -----------------------------------------------------
            ab_delay = round(trial["delay"] * CHAIN_SPLIT_RATIO, 2)
            bc_delay = round(trial["delay"] - ab_delay, 2)
            
            ab_loss = round(trial["loss"] * CHAIN_SPLIT_RATIO, 2)
            bc_loss = round(trial["loss"] - ab_loss, 2)
            
            # 第一段 (A->B)：应用 30% 损伤，限制 1000M 带宽
            set_damage("test_a", "eth0", delay=ab_delay, jitter=trial["jitter"], loss=ab_loss, bandwidth=trial["bandwidth"])
            
            # 第二段 (B->C)：应用 70% 损伤，解除带宽限制 (设为0)
            set_damage("test_b", "eth1", delay=bc_delay, jitter=trial["jitter"], loss=bc_loss, bandwidth=0)
            
            # 测量端到端数据
            measurement = _measure("172.22.0.3")
            if measurement is None:
                print(f" 跳过链式参数组 {trial}: 未获取到有效数据")
                continue
                
            avg_rtt, measured_loss, throughput = measurement
            
            # 记录数据 (注意 BC 带宽被真实记录为 0)
            save_result([
                "test_a-->test_b-->test_c",
                {"AB_delay": ab_delay, "AB_jitter": trial["jitter"], "AB_loss": ab_loss, "AB_bandwidth": trial["bandwidth"]},
                {"BC_delay": bc_delay, "BC_jitter": trial["jitter"], "BC_loss": bc_loss, "BC_bandwidth": 0},
                avg_rtt, measured_loss, throughput,
            ], "chain")
            
            time.sleep(1)
            
    # 生成相关对比图表
    print("\n 正在生成链式拓扑图表与对比分析图...")
    generate_plot("chain")
    generate_plot("comparison")


if __name__ == "__main__":
    print("\n 开始执行自动化批量网络损伤测试...\n")
    archive_history_data()
    run_auto_star()
    run_auto_chain()
    print("\n 所有自动化测试与图表生成完成！")
