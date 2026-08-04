"""
可视化绘图模块，负责解析 SQLite 数据库并生成对应的折线图、热力图与叠加柱状图。
"""

import sqlite3
import os
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict

# =====================================
# 目录与 SQLite 数据解析逻辑 (防混叠重构版)
# =====================================
DB_PATH = "data/simulation_results.db"

def create_dir(topology):
    """创建并返回图表保存目录"""
    path = f"images/{topology}"
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def read_star_data():
    """读取星型拓扑数据，按链路严格隔离，防止数据混叠"""
    if not os.path.exists(DB_PATH):
        print("[跳过] 未找到 SQLite 数据库文件")
        return [], []

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row 
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM test_results WHERE topology_type = 'star'")
        rows = cursor.fetchall()

    test_b, test_c = [], []
    for row in rows:
        data = {
            "delay": float(row["delay"] or 0),
            "jitter": float(row["jitter"] or 0),
            "loss": float(row["loss"] or 0),
            "bandwidth": float(row["bandwidth"] or 0),
            "rtt": float(row["avg_rtt"] or 0),
            "real_loss": float(row["real_loss"] or 0),
            "throughput": float(row["throughput"] or 0)
        }
        
        if row["link_name"] == "test_a-->test_b":
            test_b.append(data)
        elif row["link_name"] == "test_a-->test_c":
            test_c.append(data)

    return test_b, test_c


def read_chain_data():
    """读取链式拓扑数据，处理叠加计算"""
    if not os.path.exists(DB_PATH):
        print("[跳过] 未找到 SQLite 数据库文件")
        return []

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM test_results WHERE topology_type = 'chain'")
        rows = cursor.fetchall()

    result = []
    for row in rows:
        ab_delay = float(row["ab_delay"] or 0)
        bc_delay = float(row["bc_delay"] or 0)
        ab_loss = float(row["ab_loss"] or 0)
        bc_loss = float(row["bc_loss"] or 0)

        result.append({
            "ab_delay": ab_delay,
            "bc_delay": bc_delay,
            "delay": ab_delay + bc_delay,
            
            "ab_loss": ab_loss,
            "bc_loss": bc_loss,
            "loss": ab_loss + bc_loss,
            
            "rtt": float(row["avg_rtt"] or 0),
            "real_loss": float(row["real_loss"] or 0),
            "throughput": float(row["throughput"] or 0)
        })

    return result


def read_mesh_data():
    """读取网状拓扑数据，按动态链路名自动聚类"""
    if not os.path.exists(DB_PATH):
        print("[跳过] 未找到 SQLite 数据库文件")
        return {}

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM test_results WHERE topology_type = 'mesh'")
        rows = cursor.fetchall()

    datasets = defaultdict(list)
    for row in rows:
        data = {
            "delay": float(row["delay"] or 0),
            "jitter": float(row["jitter"] or 0),
            "loss": float(row["loss"] or 0),
            "bandwidth": float(row["bandwidth"] or 0),
            "rtt": float(row["avg_rtt"] or 0),
            "real_loss": float(row["real_loss"] or 0),
            "throughput": float(row["throughput"] or 0)
        }
        datasets[row["link_name"]].append(data)

    return datasets


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
# 核心通用绘图函数 (保留了原有的数值标注逻辑)
# =====================================

def _draw_line_chart(datasets, path, name, x_key, y_key, filter_key, x_label, y_label, title, add_baseline=False):
    """
    通用多数据源折线图绘制函数。
    """
    figure, axis = plt.subplots(figsize=(8, 5))
    has_data = False
    max_x = 0

    for i, (label, data) in enumerate(datasets.items()):
        filtered = [x for x in data if x[filter_key] == 0]
        if not filtered:
            continue

        x_values, means, deviations = _group_mean(filtered, x_key, y_key)
        if not x_values:
            continue

        has_data = True
        max_x = max(max_x, max(x_values))
        
        line = axis.errorbar(x_values, means, yerr=deviations, marker="o", linewidth=2, capsize=4, label=f"{label} {y_key.upper()}")
        
        if i % 2 == 0:
            y_offset = 6        
            v_align = 'bottom'  
        else:
            y_offset = -12      
            v_align = 'top'     

        for x, y in zip(x_values, means):
            axis.annotate(f"{y:.1f}", 
                          xy=(x, y), 
                          xytext=(0, y_offset), 
                          textcoords='offset points', 
                          ha='center', va=v_align, 
                          fontsize=9, color=line[0].get_color(),
                          fontweight='bold')

    if not has_data:
        plt.close(figure)
        return

    if add_baseline:
        axis.plot([0, max_x], [0, max_x], color="red", linestyle="--", linewidth=2, label="Ideal Baseline (y=x)")

    axis.set(xlabel=x_label, ylabel=y_label, title=title)
    axis.grid(True, alpha=0.3)
    axis.legend()
    figure.tight_layout()
    figure.savefig(f"{path}/{name}_{x_key}_{y_key}.png", dpi=220, bbox_inches="tight")
    plt.close(figure)


def _draw_composition_bar(data, path, name, param_type, ab_key, bc_key, total_key, measure_key, x_label, y_label):
    """
    通用链式拓扑叠加关系分组柱状图绘制函数。
    """
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
    
    bars1 = axis.bar(x_indices - width, ab_vals, width=width, label="Configured a->b")
    bars2 = axis.bar(x_indices, bc_vals, width=width, label="Configured b->c")
    bars3 = axis.bar(x_indices + width, measured_vals, width=width, label="Measured a->c")
    
    def autolabel(rects):
        for rect in rects:
            height = rect.get_height()
            if height > 0: 
                axis.annotate(f'{height:.1f}',
                              xy=(rect.get_x() + rect.get_width() / 2, height),
                              xytext=(0, 3), 
                              textcoords="offset points",
                              ha='center', va='bottom', fontsize=8)

    autolabel(bars1)
    autolabel(bars2)
    autolabel(bars3)
    
    axis.set(xlabel=x_label, ylabel=y_label, title=f"{name} {param_type.capitalize()} Superposition (a->b + b->c = a->c)")
    axis.set_xticks(x_indices)
    axis.set_xticklabels([f"{x:g}" for x in x_vals])
    axis.legend()
    axis.grid(True, alpha=0.3, axis='y')
    figure.tight_layout()
    figure.savefig(f"{path}/{name}_{param_type}_composition_bar.png", dpi=220, bbox_inches="tight")
    plt.close(figure)


# =====================================
# 具体图表调用接口 
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
    _draw_composition_bar(data, path, name, "delay", "ab_delay", "bc_delay", "delay", "rtt", "Total Configured Delay (ms)", "Time (ms)")
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
        
        draw_delay(datasets, path, "star_merged")
        draw_delay_throughput(datasets, path, "star_merged")
        draw_loss(datasets, path, "star_merged")
        draw_loss_measured(datasets, path, "star_merged")

        draw_heatmap(b, path, "test_a_to_test_b")
        draw_heatmap(c, path, "test_a_to_test_c")

    elif topology_type == "chain":
        data = read_chain_data()
        datasets = {
            "test_a-->test_b-->test_c": data
        }
        
        draw_delay(datasets, path, "chain")
        draw_delay_throughput(datasets, path, "chain")
        draw_loss(datasets, path, "chain")
        draw_loss_measured(datasets, path, "chain")
        
        draw_chain_composition_bar(data, path, "chain")
        draw_heatmap(data, path, "chain")

    elif topology_type == "mesh":
        datasets = read_mesh_data()
        if not datasets:
            return
            
        draw_delay(datasets, path, "mesh_merged")
        draw_delay_throughput(datasets, path, "mesh_merged")
        draw_loss(datasets, path, "mesh_merged")
        draw_loss_measured(datasets, path, "mesh_merged")

        for link_name, data in datasets.items():
            safe_name = link_name.replace("<-->", "_to_").replace(" ", "")
            draw_heatmap(data, path, safe_name)


if __name__ == "__main__":
    print("[处理中] 正在生成星型拓扑图表...")
    generate_plot("star")
    
    print("[处理中] 正在生成链式拓扑图表 (包含内部叠加成分柱状图)...")
    generate_plot("chain")
    
    print("[处理中] 正在生成网状拓扑图表...")
    generate_plot("mesh")
    
    print("[成功] 全部图表生成完毕！")
