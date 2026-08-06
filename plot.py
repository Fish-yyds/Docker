"""
可视化绘图模块
1. 单工具模式: 同一拓扑的不同链路合并至同一图表以展示链路差异。
2. 对比模式: 按链路拆分图表，专门用于对比该链路下的不同测试工具。
3. 链式拓扑: 绘制配置与测量值的三栏并列柱状图。
"""

import sqlite3
import os
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict

# =====================================
# 全局配置与数据解析
# =====================================
DB_PATH = "data/simulation_results.db"

def create_dir(topology):
    path = f"images/{topology}"
    if not os.path.exists(path):
        os.makedirs(path)
    return path

def read_comparison_data(topology_type):
    """读取指定拓扑的数据，并对链路名称进行标准化分类。"""
    if not os.path.exists(DB_PATH):
        return {}

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM test_results WHERE topology_type = ?", (topology_type,))
        rows = cursor.fetchall()

    datasets = defaultdict(lambda: defaultdict(list))
    
    for row in rows:
        tool_name = row["tool_name"]
        raw_link = row["link_name"].lower()
        
        # 剥离前缀，采用严格的连接符匹配以防止子串冲突
        clean_link = raw_link.replace("test_", "")
        
        if topology_type == "chain":
            logical_link = "Link_A_to_B_to_C"
        elif "a-->b" in clean_link or "a<-->b" in clean_link:
            logical_link = "Link_A_to_B"
        elif "b-->c" in clean_link or "b<-->c" in clean_link:
            logical_link = "Link_B_to_C"
        elif "a-->c" in clean_link or "a<-->c" in clean_link:
            logical_link = "Link_A_to_C"
        else:
            logical_link = raw_link

        # 参数提取与结构化
        if topology_type == "chain":
            conf_delay = float(row["ab_delay"] or 0) + float(row["bc_delay"] or 0)
            conf_loss = float(row["ab_loss"] or 0) + float(row["bc_loss"] or 0)
            conf_jitter = float(row["ab_jitter"] or 0) + float(row["bc_jitter"] or 0)
            conf_bw = float(row["ab_bandwidth"] or 0)
            
            ab_delay, bc_delay = float(row["ab_delay"] or 0), float(row["bc_delay"] or 0)
            ab_loss, bc_loss = float(row["ab_loss"] or 0), float(row["bc_loss"] or 0)
        else:
            conf_delay = float(row["delay"] or 0)
            conf_loss = float(row["loss"] or 0)
            conf_jitter = float(row["jitter"] or 0)
            conf_bw = float(row["bandwidth"] or 0)
            ab_delay, bc_delay, ab_loss, bc_loss = 0, 0, 0, 0

        data = {
            "delay": conf_delay, "jitter": conf_jitter, "loss": conf_loss, "bandwidth": conf_bw,
            "ab_delay": ab_delay, "bc_delay": bc_delay, "ab_loss": ab_loss, "bc_loss": bc_loss,
            "rtt": float(row["avg_rtt"] or 0), "real_loss": float(row["real_loss"] or 0),
            "throughput": float(row["throughput"] or 0)
        }
        datasets[logical_link][tool_name].append(data)

    return datasets

def _group_mean(rows, x_name, y_name):
    """计算分组均值与标准差。"""
    grouped = defaultdict(list)
    for row in rows:
        grouped[round(row[x_name], 6)].append(row[y_name])
    x_values = sorted(grouped)
    means = [float(np.mean(grouped[value])) for value in x_values]
    deviations = [float(np.std(grouped[value])) for value in x_values]
    return x_values, means, deviations

# =====================================
# 折线图生成引擎
# =====================================

def _draw_combined_line_chart(datasets, path, name_prefix, x_key, y_key, filter_key, x_label, y_label, title, add_baseline=False):
    """根据传入的 datasets 动态生成包含多条折线的图表。"""
    figure, axis = plt.subplots(figsize=(10, 6))
    has_data = False
    max_x = 0
    
    colors = plt.cm.tab10.colors
    markers = ["o", "s", "^", "D", "v", "p", "*", "x"]
    idx = 0

    for logical_link, tools in datasets.items():
        for tool_name, data in tools.items():
            filtered = [x for x in data if x[filter_key] == 0]
            if not filtered:
                continue

            x_values, means, deviations = _group_mean(filtered, x_key, y_key)
            if not x_values:
                continue

            has_data = True
            max_x = max(max_x, max(x_values))
            
            # 图例命名规则设定
            if "comp" in name_prefix:
                label = f"{tool_name.upper()}"
            else:
                label = f"{logical_link}"
                
            line = axis.errorbar(x_values, means, yerr=deviations, marker=markers[idx % len(markers)],
                                 linewidth=2.0, capsize=4, label=label, color=colors[idx % len(colors)])
            
            y_offset = 8 if idx % 2 == 0 else -14
            v_align = 'bottom' if idx % 2 == 0 else 'top'
            for x, y in zip(x_values, means):
                axis.annotate(f"{y:.1f}", xy=(x, y), xytext=(0, y_offset), textcoords='offset points', 
                              ha='center', va=v_align, fontsize=8, color=line[0].get_color(), fontweight='bold')
            idx += 1

    if not has_data:
        plt.close(figure)
        return

    if add_baseline:
        axis.plot([0, max_x], [0, max_x], color="red", linestyle="--", linewidth=1.5, alpha=0.6, label="Ideal Baseline (y=x)")

    axis.set(xlabel=x_label, ylabel=y_label, title=title)
    axis.grid(True, alpha=0.3)
    axis.legend(bbox_to_anchor=(1.02, 1), loc='upper left', borderaxespad=0.)
    figure.tight_layout()
    figure.savefig(f"{path}/{name_prefix}_{x_key}_{y_key}.png", dpi=220, bbox_inches="tight")
    plt.close(figure)

# =====================================
# 链式拓扑专属图表
# =====================================

def draw_chain_grouped_bars(datasets, path, name_prefix):
    """绘制链式拓扑的三栏分组柱状图。"""
    chain_data = datasets.get("Link_A_to_B_to_C", {}).get("docker_tc", [])
    if not chain_data:
        return
    
    filtered_delay = [x for x in chain_data if x["loss"] == 0 and x["delay"] > 0]
    if filtered_delay:
        _draw_grouped_bar_core(
            filtered_delay, path, f"{name_prefix}_delay_accumulation",
            sort_key="delay", val1_key="ab_delay", val2_key="bc_delay", measured_key="rtt",
            title="Chain Topology: Delay Accumulation (Three-Column)",
            y_label="Time (ms)", config_label_format="{}+{} ms"
        )
        
    filtered_loss = [x for x in chain_data if x["delay"] == 0 and x["loss"] > 0]
    if filtered_loss:
        _draw_grouped_bar_core(
            filtered_loss, path, f"{name_prefix}_loss_accumulation",
            sort_key="loss", val1_key="ab_loss", val2_key="bc_loss", measured_key="real_loss",
            title="Chain Topology: Loss Accumulation (Three-Column)",
            y_label="Loss Rate (%)", config_label_format="{}+{} %"
        )

def _draw_grouped_bar_core(data_list, path, filename, sort_key, val1_key, val2_key, measured_key, title, y_label, config_label_format):
    x_labels, val1_list, val2_list, measured_list = [], [], [], []
    for row in sorted(data_list, key=lambda x: x[sort_key]):
        label = config_label_format.format(row[val1_key], row[val2_key])
        if label not in x_labels:
            x_labels.append(label)
            val1_list.append(row[val1_key])
            val2_list.append(row[val2_key])
            measured_list.append(row[measured_key])

    if not x_labels: return

    x = np.arange(len(x_labels))
    width = 0.25
    fig, ax = plt.subplots(figsize=(10, 6))
    
    bar1 = ax.bar(x - width, val1_list, width, label=f'A->B Config', color='#1f77b4')
    bar2 = ax.bar(x, val2_list, width, label=f'B->C Config', color='#ff7f0e')
    bar3 = ax.bar(x + width, measured_list, width, label=f'A->C Measured', color='#2ca02c')

    ax.set_ylabel(y_label)
    ax.set_xlabel('Configuration Combination')
    ax.set_title(title)
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels)
    ax.legend(bbox_to_anchor=(1.02, 1), loc='upper left')
    ax.grid(True, alpha=0.3, axis='y')

    for bars in [bar1, bar2, bar3]:
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.annotate(f'{height:.1f}', (bar.get_x() + bar.get_width() / 2, height),
                            xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=8)

    fig.tight_layout()
    fig.savefig(f"{path}/{filename}.png", dpi=220)
    plt.close(fig)

# =====================================
# 热力图生成
# =====================================

def draw_heatmap(data, path, name):
    """生成综合损伤测试结果的二维热力图。"""
    if not data: return
    delays = sorted({round(x["delay"], 6) for x in data})
    losses = sorted({round(x["loss"], 6) for x in data})
    grouped = defaultdict(list)
    for x in data:
        grouped[(round(x["delay"], 6), round(x["loss"], 6))].append(x["throughput"])
    matrix = np.full((len(delays), len(losses)), np.nan)
    for i, delay in enumerate(delays):
        for j, loss in enumerate(losses):
            vals = grouped.get((delay, loss))
            if vals: matrix[i, j] = np.mean(vals)

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
# 流程控制
# =====================================

def generate_plot(topology_type, mode="single", target_tool="docker_tc"):
    """
    调度绘图模块
    :param mode: "single" 输出基础多链路合并图, "comparison" 输出单链路多工具对比图
    """
    datasets = read_comparison_data(topology_type)
    if not datasets:
        print(f"[Skip] 拓扑 {topology_type.upper()} 无可用测试数据。")
        return

    if mode == "single":
        path = create_dir(topology_type)
        filtered_datasets = defaultdict(dict)
        for link, tools in datasets.items():
            if target_tool in tools:
                filtered_datasets[link][target_tool] = tools[target_tool]
        if not filtered_datasets:
            return

        # 生成同图多线综合图表
        _draw_combined_line_chart(filtered_datasets, path, f"{topology_type}_all_links", "delay", "rtt", "loss", "Configured Delay (ms)", "Average RTT (ms)", f"{topology_type.upper()} All Links: Delay vs RTT", True)
        _draw_combined_line_chart(filtered_datasets, path, f"{topology_type}_all_links", "delay", "throughput", "loss", "Configured Delay (ms)", "Throughput (Mbps)", f"{topology_type.upper()} All Links: Delay vs Throughput", False)
        _draw_combined_line_chart(filtered_datasets, path, f"{topology_type}_all_links", "loss", "throughput", "delay", "Configured Loss (%)", "Throughput (Mbps)", f"{topology_type.upper()} All Links: Loss vs Throughput", False)
        _draw_combined_line_chart(filtered_datasets, path, f"{topology_type}_all_links", "loss", "real_loss", "delay", "Configured Loss (%)", "Measured Loss (%)", f"{topology_type.upper()} All Links: Configured vs Measured Loss", True)

        if topology_type == "chain":
            draw_chain_grouped_bars(filtered_datasets, path, f"chain_{target_tool}")
        for link, tools in filtered_datasets.items():
            draw_heatmap(tools[target_tool], path, f"{link}_{target_tool}")
            
    elif mode == "comparison":
        path = create_dir(f"{topology_type}_tool_comparison")
        
        # 按链路独立处理并输出对比图
        for logical_link, tools_data in datasets.items():
            found_tools = list(tools_data.keys())
            print(f"[Process] 处理对比视图: {logical_link}")
            print(f"  |- 数据源: {found_tools}")
            if len(found_tools) < 2:
                print(f"  |- [Warn] 数据源不足 (仅 {found_tools[0]}). 对比折线将以单线呈现。")
            else:
                print(f"  |- [OK] 满足多数据源对比条件。")

            single_link_dataset = {logical_link: tools_data}
            
            _draw_combined_line_chart(single_link_dataset, path, f"{topology_type}_{logical_link}_comp", "delay", "rtt", "loss", "Configured Delay (ms)", "Average RTT (ms)", f"{logical_link} Comparison: Delay vs RTT", True)
            _draw_combined_line_chart(single_link_dataset, path, f"{topology_type}_{logical_link}_comp", "delay", "throughput", "loss", "Configured Delay (ms)", "Throughput (Mbps)", f"{logical_link} Comparison: Delay vs Throughput", False)
            _draw_combined_line_chart(single_link_dataset, path, f"{topology_type}_{logical_link}_comp", "loss", "throughput", "delay", "Configured Loss (%)", "Throughput (Mbps)", f"{logical_link} Comparison: Loss vs Throughput", False)
            _draw_combined_line_chart(single_link_dataset, path, f"{topology_type}_{logical_link}_comp", "loss", "real_loss", "delay", "Configured Loss (%)", "Measured Loss (%)", f"{logical_link} Comparison: Configured vs Measured Loss", True)

            # 遍历输出各数据源独立热力图以供并列分析
            for tool_name, data in tools_data.items():
                draw_heatmap(data, path, f"{topology_type}_{logical_link}_comp_{tool_name}")

if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print(f"[Error] 数据库文件未找到: {DB_PATH}")
    else:
        print("[Info] 开始生成基础图表任务...")
        for topo in ["star", "chain", "mesh"]:
            print(f"[Run] 拓扑: {topo.upper()} -> 目标目录: images/{topo}/")
            generate_plot(topo, mode="single", target_tool="docker_tc")
        
        print("\n[Info] 开始生成工具对比图表任务...")
        print("[Run] 拓扑: MESH -> 目标目录: images/mesh_tool_comparison/")
        generate_plot("mesh", mode="comparison")
        
        print("\n[Info] 所有渲染作业执行完成。")
