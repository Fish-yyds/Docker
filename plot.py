"""从 SQLite 结果生成折线图、链式分组柱状图和热力图。"""

import sqlite3
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from database import DB_PATH

BASE_DIR = Path(__file__).resolve().parent

# 每项依次为：横轴字段、纵轴字段、筛选字段、横轴名、纵轴名、标题、是否绘制理想线。
CHARTS = (
    ("delay", "rtt", "loss", "Configured Delay (ms)", "Average RTT (ms)", "Delay vs RTT", True),
    ("delay", "throughput", "loss", "Configured Delay (ms)", "Throughput (Mbps)", "Delay vs Throughput", False),
    ("loss", "throughput", "delay", "Configured Loss (%)", "Throughput (Mbps)", "Loss vs Throughput", False),
    ("loss", "real_loss", "delay", "Configured Loss (%)", "Measured Loss (%)", "Configured vs Measured Loss", True),
)


def _output_dir(name):
    """创建 images/name 输出目录并返回对应 Path 对象。"""
    path = BASE_DIR / "images" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _logical_link(topology, raw_link):
    """将数据库中的 raw_link 转换为不同工具共用的标准链路名称。"""
    clean = raw_link.lower().replace("test_", "")
    if topology == "chain":
        return "Link_A_to_B_to_C"

    for token, name in (
        ("a-->b", "Link_A_to_B"),
        ("a<-->b", "Link_A_to_B"),
        ("b-->c", "Link_B_to_C"),
        ("b<-->c", "Link_B_to_C"),
        ("a-->c", "Link_A_to_C"),
        ("a<-->c", "Link_A_to_C"),
    ):
        if token in clean:
            return name
    return raw_link


def read_comparison_data(topology_type):
    """读取 topology_type 的有效记录，返回“链路 -> 工具 -> 数据列表”。"""
    if not DB_PATH.exists():
        return {}

    # 只读取吞吐量有效且未完全丢包的记录。
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM test_results "
            "WHERE topology_type = ? AND throughput > 0 AND real_loss < 100 "
            "ORDER BY id",
            (topology_type,),
        ).fetchall()

    datasets = defaultdict(lambda: defaultdict(list))
    for row in rows:
        # 链式拓扑需要合并 A-B 和 B-C 两段配置。
        if topology_type == "chain":
            ab_delay, bc_delay = float(row["ab_delay"] or 0), float(row["bc_delay"] or 0)
            ab_loss, bc_loss = float(row["ab_loss"] or 0), float(row["bc_loss"] or 0)
            delay, loss = ab_delay + bc_delay, ab_loss + bc_loss
            jitter = float(row["ab_jitter"] or 0) + float(row["bc_jitter"] or 0)
            bandwidth = float(row["ab_bandwidth"] or 0)
        else:
            delay, loss = float(row["delay"] or 0), float(row["loss"] or 0)
            jitter, bandwidth = float(row["jitter"] or 0), float(row["bandwidth"] or 0)
            ab_delay = bc_delay = ab_loss = bc_loss = 0.0

        data = {
            "delay": delay,
            "jitter": jitter,
            "loss": loss,
            "bandwidth": bandwidth,
            "ab_delay": ab_delay,
            "bc_delay": bc_delay,
            "ab_loss": ab_loss,
            "bc_loss": bc_loss,
            "rtt": float(row["avg_rtt"] or 0),
            "real_loss": float(row["real_loss"] or 0),
            "throughput": float(row["throughput"] or 0),
        }
        link = _logical_link(topology_type, row["link_name"])
        datasets[link][row["tool_name"]].append(data)

    return datasets


def _group_mean(rows, x_key, y_key):
    """按照 x_key 分组，返回横轴值、y_key 均值及标准差。"""
    grouped = defaultdict(list)
    for row in rows:
        grouped[round(row[x_key], 6)].append(row[y_key])

    x_values = sorted(grouped)
    return (
        x_values,
        [float(np.mean(grouped[x])) for x in x_values],
        [float(np.std(grouped[x])) for x in x_values],
    )


def _draw_lines(datasets, path, prefix, spec, comparison):
    """根据 spec 绘制折线图；comparison 决定图例显示工具还是链路。"""
    x_key, y_key, filter_key, x_label, y_label, subtitle, baseline = spec
    figure, axis = plt.subplots(figsize=(10, 6))
    count, max_x = 0, 0
    markers = ("o", "s", "^", "D", "v", "p", "*", "x")

    for link, tools in datasets.items():
        for tool, rows in tools.items():
            # 研究单一变量时，要求另一个损伤参数为 0。
            filtered = [row for row in rows if row[filter_key] == 0]
            if not filtered:
                continue

            x_values, means, deviations = _group_mean(filtered, x_key, y_key)
            max_x = max(max_x, max(x_values))
            label = tool.upper() if comparison else link
            line = axis.errorbar(
                x_values,
                means,
                yerr=deviations,
                marker=markers[count % len(markers)],
                linewidth=2,
                capsize=4,
                label=label,
            )

            # 在每个数据点上标注平均值。
            for x, y in zip(x_values, means):
                axis.annotate(
                    f"{y:.1f}",
                    (x, y),
                    xytext=(0, 7),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                    color=line[0].get_color(),
                )
            count += 1

    if not count:
        plt.close(figure)
        return

    # RTT 和实测丢包率图使用 y=x 作为理想参考线。
    if baseline:
        axis.plot(
            [0, max_x],
            [0, max_x],
            "r--",
            linewidth=1.5,
            alpha=0.6,
            label="Ideal y=x",
        )

    axis.set(xlabel=x_label, ylabel=y_label, title=f"{prefix}: {subtitle}")
    axis.grid(True, alpha=0.3)
    axis.legend(bbox_to_anchor=(1.02, 1), loc="upper left")
    figure.tight_layout()
    figure.savefig(path / f"{prefix}_{x_key}_{y_key}.png", dpi=220, bbox_inches="tight")
    plt.close(figure)


def _draw_chain_bars(datasets, path):
    """绘制链式拓扑两段配置值与端到端实测值的分组柱状图。"""
    rows = datasets.get("Link_A_to_B_to_C", {}).get("docker_tc", [])
    groups = (
        (
            [row for row in rows if row["loss"] == 0 and row["delay"] > 0],
            "delay", "ab_delay", "bc_delay", "rtt", "Time (ms)",
        ),
        (
            [row for row in rows if row["delay"] == 0 and row["loss"] > 0],
            "loss", "ab_loss", "bc_loss", "real_loss", "Loss Rate (%)",
        ),
    )

    for data, sort_key, left_key, right_key, measured_key, ylabel in groups:
        if not data:
            continue

        # 相同两段配置只保留一组实测结果。
        unique = {}
        for row in sorted(data, key=lambda item: item[sort_key]):
            unique.setdefault((row[left_key], row[right_key]), row[measured_key])

        labels = [f"{left:g}+{right:g}" for left, right in unique]
        left = [key[0] for key in unique]
        right = [key[1] for key in unique]
        measured = list(unique.values())
        x, width = np.arange(len(labels)), 0.25

        figure, axis = plt.subplots(figsize=(10, 6))
        bars = (
            axis.bar(x - width, left, width, label="A->B Config"),
            axis.bar(x, right, width, label="B->C Config"),
            axis.bar(x + width, measured, width, label="A->C Measured"),
        )
        for collection in bars:
            axis.bar_label(collection, fmt="%.1f", padding=3, fontsize=8)

        axis.set(
            xlabel="Configuration Combination",
            ylabel=ylabel,
            title=f"Chain {sort_key.title()} Accumulation",
        )
        axis.set_xticks(x, labels)
        axis.grid(True, alpha=0.3, axis="y")
        axis.legend()
        figure.tight_layout()
        figure.savefig(path / f"chain_{sort_key}_accumulation.png", dpi=220)
        plt.close(figure)


def _draw_heatmap(rows, path, name):
    """根据 rows 绘制时延、丢包率与平均吞吐量之间的热力图。"""
    if not rows:
        return

    delays = sorted({round(row["delay"], 6) for row in rows})
    losses = sorted({round(row["loss"], 6) for row in rows})
    grouped = defaultdict(list)

    # 相同参数可能有多轮结果，因此先按时延和丢包率分组。
    for row in rows:
        key = (round(row["delay"], 6), round(row["loss"], 6))
        grouped[key].append(row["throughput"])

    matrix = np.full((len(delays), len(losses)), np.nan)
    for i, delay in enumerate(delays):
        for j, loss in enumerate(losses):
            values = grouped.get((delay, loss))
            if values:
                matrix[i, j] = np.mean(values)

    figure, axis = plt.subplots(figsize=(9, 6))
    image = axis.imshow(matrix, origin="lower", aspect="auto", cmap="viridis")
    axis.set_xticks(range(len(losses)), [f"{value:g}" for value in losses])
    axis.set_yticks(range(len(delays)), [f"{value:g}" for value in delays])
    axis.set(
        xlabel="Configured Loss (%)",
        ylabel="Configured Delay (ms)",
        title=f"{name} Throughput Heatmap",
    )

    # 在热力图单元格中显示吞吐量，无数据时显示 --。
    for i, row in enumerate(matrix):
        for j, value in enumerate(row):
            text = "--" if np.isnan(value) else f"{value:.1f}"
            axis.text(j, i, text, ha="center", va="center", fontsize=8)

    figure.colorbar(image, ax=axis, label="Throughput (Mbps)")
    figure.tight_layout()
    figure.savefig(path / f"{name}_heatmap.png", dpi=220, bbox_inches="tight")
    plt.close(figure)


def generate_plot(topology_type, mode="single", target_tool="docker_tc"):
    """生成图表；topology_type 指定拓扑，mode 指定单工具或对比模式。"""
    if mode not in {"single", "comparison"}:
        raise ValueError(f"不支持的绘图模式：{mode}")

    datasets = read_comparison_data(topology_type)
    if not datasets:
        print(f"[未执行] {topology_type.upper()} 没有有效测量数据。")
        return

    comparison = mode == "comparison"
    directory = f"{topology_type}_tool_comparison" if comparison else topology_type
    path = _output_dir(directory)
    selected = datasets

    # 单工具模式只保留 target_tool 对应的数据。
    if not comparison:
        selected = {
            link: {target_tool: tools[target_tool]}
            for link, tools in datasets.items()
            if target_tool in tools
        }
        if not selected:
            print(f"[未执行] 没有工具 {target_tool} 的有效 {topology_type} 数据。")
            return

    # 对比模式每条链路单独比较工具；单工具模式在一张图中比较链路。
    groups = selected.items() if comparison else ((topology_type.upper(), selected),)
    for link, tools in groups:
        subset = {link: tools} if comparison else tools
        prefix = (
            f"{topology_type}_{link}_comparison"
            if comparison
            else f"{topology_type}_all_links"
        )
        for spec in CHARTS:
            _draw_lines(subset, path, prefix, spec, comparison)

        if comparison:
            for tool, rows in tools.items():
                _draw_heatmap(rows, path, f"{link}_{tool}")

    if topology_type == "chain" and not comparison:
        _draw_chain_bars(selected, path)

    if not comparison:
        for link, tools in selected.items():
            _draw_heatmap(tools[target_tool], path, f"{link}_{target_tool}")

    print(f"[完成] 图表已生成：{path}")


if __name__ == "__main__":
    # 直接运行 plot.py 时生成三种 Docker 图表及网状拓扑工具对比图。
    for topology in ("star", "chain", "mesh"):
        generate_plot(topology)
    generate_plot("mesh", mode="comparison")