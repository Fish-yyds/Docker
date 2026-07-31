"""
可视化绘图模块，负责解析网络测试数据并生成对应的折线图、热力图与叠加柱状图。
"""

import re
import os
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict

# =====================================
# 目录与数据解析逻辑
# =====================================

def create_dir(topology):
    """创建并返回图表保存目录"""
    path = f"images/{topology}"
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def read_star_data():
    """读取并解析星型拓扑数据"""
    filename = "data/star_data.txt"
    if not os.path.exists(filename):
        print("未找到星型数据文件")
        return [], []

    with open(filename, "r", encoding="utf-8") as f:
        text = f.read()

    blocks = text.split("==============================")
    test_b, test_c = [], []

    for block in blocks:
        if "test_a-->test_b" in block:
            link = "b"
        elif "test_a-->test_c" in block:
            link = "c"
        else:
            continue

        delay = re.search(r'延迟\(delay\):([\d.]+)', block)
        jitter = re.search(r'抖动\(jitter\):([\d.]+)', block)
        loss = re.search(r'丢包\(loss\):([\d.]+)', block)
        bandwidth = re.search(r'带宽\(bandwidth\):([\d.]+)', block)
        rtt = re.search(r'平均RTT:([\d.]+)', block)
        real_loss = re.search(r'实际丢包率:([\d.]+)', block)
        throughput = re.search(r'吞吐量:([\d.]+)', block)

        if not (delay and loss and throughput):
            continue

        data = {
            "delay": float(delay.group(1)),
            "jitter": float(jitter.group(1)) if jitter else 0,
            "loss": float(loss.group(1)),
            "bandwidth": float(bandwidth.group(1)) if bandwidth else 0,
            "rtt": float(rtt.group(1)) if rtt else 0,
            "real_loss": float(real_loss.group(1)) if real_loss else 0,
            "throughput": float(throughput.group(1))
        }

        if link == "b":
            test_b.append(data)
        else:
            test_c.append(data)

    return test_b, test_c


def read_chain_data():
    """读取并解析链式拓扑数据，保留单段链路设定值用于叠加分析"""
    filename = "data/chain_data.txt"
    if not os.path.exists(filename):
        print("未找到链式数据文件")
        return []

    with open(filename, "r", encoding="utf-8") as f:
        text = f.read()

    blocks = text.split("==============================")
    result = []

    for block in blocks:
        if "test_a-->test_b-->test_c" not in block:
            continue

        ab_delay = re.search(r'第一段链路.*?延迟\(delay\):([\d.]+)', block, re.S)
        bc_delay = re.search(r'第二段链路.*?延迟\(delay\):([\d.]+)', block, re.S)
        ab_loss = re.search(r'第一段链路.*?丢包\(loss\):([\d.]+)', block, re.S)
        bc_loss = re.search(r'第二段链路.*?丢包\(loss\):([\d.]+)', block, re.S)
        rtt = re.search(r'平均RTT:([\d.]+)', block)
        real_loss = re.search(r'实际丢包率:([\d.]+)', block)
        throughput = re.search(r'吞吐量:([\d.]+)', block)

        if not (ab_delay and bc_delay and ab_loss and bc_loss and throughput):
            continue

        result.append({
            "ab_delay": float(ab_delay.group(1)),
            "bc_delay": float(bc_delay.group(1)),
            "delay": float(ab_delay.group(1)) + float(bc_delay.group(1)),
            
            "ab_loss": float(ab_loss.group(1)),
            "bc_loss": float(bc_loss.group(1)),
            "loss": float(ab_loss.group(1)) + float(bc_loss.group(1)),
            
            "rtt": float(rtt.group(1)) if rtt else 0,
            "real_loss": float(real_loss.group(1)) if real_loss else 0,
            "throughput": float(throughput.group(1))
        })

    return result


def _group_mean(rows, x_name, y_name):
    """提取数据的均值与标准差，用于绘制误差棒"""
    grouped = defaultdict(list)
    for row in rows:
        grouped[round(row[x_name], 6)].append(row[y_name])
    
    x_values = sorted(grouped)
    means = [float(np.mean(grouped[value])) for value in x_values]
    deviations = [float(np.std(grouped[value])) for value in x_values]
    return x_values, means, deviations


# =====================================
# 核心通用绘图函数 (解决代码冗余的关键)
# =====================================

def _draw_line_chart(datasets, path, name, x_key, y_key, filter_key, x_label, y_label, title, add_baseline=False):
    """
    通用多数据源折线图绘制函数。
    支持合并画图、误差棒绘制以及理论基准线自动生成。
    """
    figure, axis = plt.subplots(figsize=(8, 5))
    has_data = False
    max_x = 0

    for label, data in datasets.items():
        # 过滤控制变量：例如当看 delay 影响时，必须保证 loss == 0
        filtered = [x for x in data if x[filter_key] == 0]
        if not filtered:
            continue

        x_values, means, deviations = _group_mean(filtered, x_key, y_key)
        if not x_values:
            continue

        has_data = True
        max_x = max(max_x, max(x_values))
        axis.errorbar(x_values, means, yerr=deviations, marker="o", linewidth=2, capsize=4, label=f"{label} {y_key.upper()}")

    if not has_data:
        plt.close(figure)
        return

    # 动态追加基准线 (y=x)
    if add_baseline:
        axis.plot([0, max_x], [0, max_x], color="red", linestyle="--", linewidth=2, label="Ideal Baseline (y=x)")

    axis.set(xlabel=x_label, ylabel=y_label, title=title)
    axis.grid(True, alpha=0.3)
    axis.legend()
    figure.tight_layout()
    # 动态命名文件
    figure.savefig(f"{path}/{name}_{x_key}_{y_key}.png", dpi=220, bbox_inches="tight")
    plt.close(figure)


def _draw_composition_bar(data, path, name, param_type, ab_key, bc_key, total_key, measure_key, x_label, y_label):
    """
    通用链式拓扑叠加关系分组柱状图绘制函数。
    """
    # 过滤控制变量：看延迟叠加时去丢包，看丢包叠加时去延迟
    filter_key = "loss" if param_type == "delay" else "delay"
    filtered = [x for x in data if x[filter_key] == 0]
    
    if not filtered:
        return

    grouped = defaultdict(list)
    for row in filtered:
        grouped[round(row[total_key], 6)].append(row)
    
    x_vals = sorted(grouped.keys())
    ab_vals = [np.mean([r[ab_key] for r in grouped[x]]) for x in x_vals]
    bc_vals = [np.mean([r[bc_key] for r in grouped[x]]) for x in x_vals]
    measured_vals = [np.mean([r[measure_key] for r in grouped[x]]) for x in x_vals]
    
    x_indices = np.arange(len(x_vals))
    width = 0.25
    
    figure, axis = plt.subplots(figsize=(10, 6))
    axis.bar(x_indices - width, ab_vals, width=width, label="Configured a->b")
    axis.bar(x_indices, bc_vals, width=width, label="Configured b->c")
    axis.bar(x_indices + width, measured_vals, width=width, label="Measured a->c")
    
    axis.set(xlabel=x_label, ylabel=y_label, title=f"{name} {param_type.capitalize()} Superposition (a->b + b->c = a->c)")
    axis.set_xticks(x_indices)
    axis.set_xticklabels([f"{x:g}" for x in x_vals])
    axis.legend()
    axis.grid(True, alpha=0.3, axis='y')
    figure.tight_layout()
    figure.savefig(f"{path}/{name}_{param_type}_composition_bar.png", dpi=220, bbox_inches="tight")
    plt.close(figure)


# =====================================
# 具体图表调用接口 (保持向后兼容的文件名体系)
# =====================================

def draw_delay(datasets, path, name):
    _draw_line_chart(datasets, path, name, "delay", "rtt", "loss", "Configured Delay (ms)", "Average RTT (ms)", f"{name} Delay vs RTT", True)

def draw_delay_throughput(datasets, path, name):
    _draw_line_chart(datasets, path, name, "delay", "throughput", "loss", "Configured Delay (ms)", "Throughput (Mbps)", f"{name} Delay vs Throughput", False)

def draw_loss(datasets, path, name):
    _draw_line_chart(datasets, path, name, "loss", "throughput", "delay", "Configured Loss (%)", "Throughput (Mbps)", f"{name} Loss vs Throughput", False)

def draw_loss_measured(datasets, path, name):
    _draw_line_chart(datasets, path, name, "loss", "real_loss", "delay", "Configured Loss (%)", "Measured Loss (%)", f"{name} Configured vs Measured Loss", True)

def draw_chain_composition_bar(data, path, name):
    # 绘制延迟叠加柱状图
    _draw_composition_bar(data, path, name, "delay", "ab_delay", "bc_delay", "delay", "rtt", "Total Configured Delay (ms)", "Time (ms)")
    # 绘制丢包叠加柱状图
    _draw_composition_bar(data, path, name, "loss", "ab_loss", "bc_loss", "loss", "real_loss", "Total Configured Loss (%)", "Loss Rate (%)")


def draw_heatmap(data, path, name):
    """综合损伤热力图"""
    if not data:
        return

    delays = sorted({round(x["delay"], 6) for x in data})
    losses = sorted({round(x["loss"], 6) for x in data})
    
    grouped = defaultdict(list)
    for x in data:
        grouped[(round(x["delay"], 6), round(x["loss"], 6))].append(x["throughput"])

    matrix = np.full((len(delays), len(losses)), np.nan)
    
    for i, delay in enumerate(delays):
        for j, loss in enumerate(losses):
            vals = grouped.get((delay, loss))
            if vals:
                matrix[i, j] = np.mean(vals)

    figure, axis = plt.subplots(figsize=(9, 6))
    image = axis.imshow(matrix, origin="lower", aspect="auto", cmap="viridis")

    axis.set_xticks(range(len(losses)))
    axis.set_xticklabels([f"{val:g}" for val in losses])
    axis.set_yticks(range(len(delays)))
    axis.set_yticklabels([f"{val:g}" for val in delays])
    
    axis.set(xlabel="Configured Loss (%)", ylabel="Configured Delay (ms)", title=f"{name} Delay-Loss-Throughput Heatmap")
    midpoint = (np.nanmin(matrix) + np.nanmax(matrix)) / 2
    
    for i in range(len(delays)):
        for j in range(len(losses)):
            value = matrix[i, j]
            label = "--" if np.isnan(value) else f"{value:.1f}"
            color = "white" if not np.isnan(value) and value < midpoint else "black"
            axis.text(j, i, label, ha="center", va="center", color=color, fontsize=9)
            
    figure.colorbar(image, ax=axis, label="Throughput (Mbps)")
    figure.tight_layout()
    figure.savefig(f"{path}/{name}_heatmap.png", dpi=220, bbox_inches="tight")
    plt.close(figure)


# =====================================
# 主入口
# =====================================

def generate_plot(topology_type):
    """
    根据给定的拓扑类型，读取对应数据并批量生成测试报告图表。
    """
    path = create_dir(topology_type)

    if topology_type == "star":
        b, c = read_star_data()
        datasets = {
            "test_a-->test_b": b,
            "test_a-->test_c": c
        }
        
        # 折线图合并渲染
        draw_delay(datasets, path, "star_merged")
        draw_delay_throughput(datasets, path, "star_merged")
        draw_loss(datasets, path, "star_merged")
        draw_loss_measured(datasets, path, "star_merged")

        # 热力图独立渲染
        draw_heatmap(b, path, "test_a_to_test_b")
        draw_heatmap(c, path, "test_a_to_test_c")

    elif topology_type == "chain":
        data = read_chain_data()
        datasets = {
            "test_a-->test_b-->test_c": data
        }
        
        # 1. 绘制单链路基准对比折线图
        draw_delay(datasets, path, "chain")
        draw_delay_throughput(datasets, path, "chain")
        draw_loss(datasets, path, "chain")
        draw_loss_measured(datasets, path, "chain")
        
        # 2. 绘制链式拓扑内部的叠加关系验证柱状图
        draw_chain_composition_bar(data, path, "chain")
        
        # 3. 绘制热力图
        draw_heatmap(data, path, "chain")


if __name__ == "__main__":
    print("正在生成星型拓扑图表...")
    generate_plot("star")
    
    print("正在生成链式拓扑图表 (包含内部叠加成分柱状图)...")
    generate_plot("chain")
    
    print("全部图表生成完毕！")
