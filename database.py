"""使用 TXT 格式保存测试测量数据。"""

from datetime import datetime
from pathlib import Path

# ==================================
# 全局路径配置
# ==================================
DATA_DIR = Path("data")
RESULT_FILES = {
    "star": DATA_DIR / "star_data.txt",
    "chain": DATA_DIR / "chain_data.txt",
}

def result_path(topology_type):
    """
    获取指定拓扑的数据保存路径（也用于 auto_test 脚本备份历史文件）。
    """
    try:
        return RESULT_FILES[topology_type]
    except KeyError as error:
        raise ValueError(f"不支持的拓扑类型: {topology_type}") from error


# ==================================
# 文本格式化辅助函数
# ==================================
def _format_damage(delay, jitter, loss, bandwidth):
    """[内部函数] 统一格式化单段链路损伤参数文本。"""
    return (
        f"延迟(delay):{delay} ms\n"
        f"抖动(jitter):{jitter} ms\n"
        f"丢包(loss):{loss}%\n"
        f"带宽(bandwidth):{bandwidth} Mbps\n"
    )

def _format_result(avg_rtt, real_loss, throughput):
    """[内部函数] 统一格式化实际测量结果文本。"""
    return (
        f"平均RTT:{avg_rtt} ms\n"
        f"实际丢包率:{real_loss}%\n"
        f"吞吐量:{throughput} Mbps\n"
    )

def _format_star(data):
    """[内部函数] 组装星型拓扑的完整测试报告。"""
    target, delay, jitter, loss, bandwidth, avg_rtt, real_loss, throughput = data
    link = {"test_b": "test_a-->test_b", "test_c": "test_a-->test_c"}.get(target, "unknown")
    
    # 去除微秒，格式化为整洁时间
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    return (
        f"实验时间:{timestamp}\n"
        "拓扑类型:星型拓扑\n"
        f"链路:{link}\n\n"
        "损伤参数:\n"
        f"{_format_damage(delay, jitter, loss, bandwidth)}\n"
        "测试结果:\n"
        f"{_format_result(avg_rtt, real_loss, throughput)}"
    )

def _format_chain(data):
    """[内部函数] 组装链式拓扑的完整测试报告。"""
    link, ab, bc, avg_rtt, real_loss, throughput = data
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    return (
        f"实验时间:{timestamp}\n"
        "拓扑类型:链式拓扑\n"
        f"链路:{link}\n\n"
        "第一段链路(test_a-->test_b)损伤参数:\n"
        f"{_format_damage(ab['AB_delay'], ab['AB_jitter'], ab['AB_loss'], ab['AB_bandwidth'])}\n"
        "第二段链路(test_b-->test_c)损伤参数:\n"
        f"{_format_damage(bc['BC_delay'], bc['BC_jitter'], bc['BC_loss'], bc['BC_bandwidth'])}\n"
        "端到端测试结果(test_a-->test_c):\n"
        f"{_format_result(avg_rtt, real_loss, throughput)}"
    )


# ==================================
# 核心保存逻辑
# ==================================
def save_result(data, topology_type):
    """
    以追加模式保存单次测量记录，保持项目的原始文本布局，供绘图正则解析。
    
    :param data: 测量参数与结果的组合列表
    :param topology_type: "star" 或 "chain"
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # 动态匹配格式化函数
    formatters = {"star": _format_star, "chain": _format_chain}
    if topology_type not in formatters:
        raise ValueError(f"不支持的拓扑类型: {topology_type}")

    path = result_path(topology_type)
    formatter = formatters[topology_type]
    
    with path.open("a", encoding="utf-8") as handle:
        handle.write("==============================\n")
        handle.write(formatter(data))
        handle.write("==============================\n\n")
        
    print(f" 实验数据已保存到: {path}")
    return path
