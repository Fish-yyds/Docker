"""使用 SQLite 结构化存储测试测量数据。"""

import sqlite3
from datetime import datetime
from pathlib import Path

# ==================================
# 全局路径与数据库配置
# ==================================
DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "simulation_results.db"

def init_db():
    """初始化 SQLite 数据库，自动建表"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        # 创建统一的数据总表，利用可空字段兼容不同的拓扑参数
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                topology_type TEXT NOT NULL,
                link_name TEXT NOT NULL,
                
                -- 通用与单链路损伤参数 (Star, Mesh)
                delay REAL,
                jitter REAL,
                loss REAL,
                bandwidth REAL,
                
                -- 链式拓扑专用损伤参数 (Chain)
                ab_delay REAL,
                ab_jitter REAL,
                ab_loss REAL,
                ab_bandwidth REAL,
                bc_delay REAL,
                bc_jitter REAL,
                bc_loss REAL,
                bc_bandwidth REAL,
                
                -- 测试结果指标
                avg_rtt REAL,
                real_loss REAL,
                throughput REAL
            )
        ''')
        conn.commit()

# 模块加载时自动建表
init_db()

def result_path(topology_type=None):
    """
    返回数据库路径。
    保留此函数和 topology_type 参数，是为了向下兼容 auto_test.py 中的 archive_history_data 备份逻辑。
    """
    return DB_PATH


# ==================================
# 数据解析辅助函数
# ==================================
def _parse_star_or_mesh(data, topology_type):
    """解析星型与网状拓扑的单链路数据"""
    target_or_link, delay, jitter, loss, bandwidth, avg_rtt, real_loss, throughput = data
    
    # 格式化星型拓扑的链路名称
    link = target_or_link
    if topology_type == "star" and target_or_link in ["test_b", "test_c"]:
        link = f"test_a-->{target_or_link}"
        
    return {
        "topology_type": topology_type,
        "link_name": link,
        "delay": delay, "jitter": jitter, "loss": loss, "bandwidth": bandwidth,
        "avg_rtt": avg_rtt, "real_loss": real_loss, "throughput": throughput
    }

def _parse_chain(data):
    """解析链式拓扑的级联双链路数据"""
    link, ab, bc, avg_rtt, real_loss, throughput = data
    
    return {
        "topology_type": "chain",
        "link_name": link,
        "ab_delay": ab['AB_delay'], "ab_jitter": ab['AB_jitter'], 
        "ab_loss": ab['AB_loss'], "ab_bandwidth": ab['AB_bandwidth'],
        "bc_delay": bc['BC_delay'], "bc_jitter": bc['BC_jitter'], 
        "bc_loss": bc['BC_loss'], "bc_bandwidth": bc['BC_bandwidth'],
        "avg_rtt": avg_rtt, "real_loss": real_loss, "throughput": throughput
    }


# ==================================
# 核心保存逻辑
# ==================================
def save_result(data, topology_type):
    """
    将单次测量记录直接插入到 SQLite 数据库中。
    
    :param data: 测量参数与结果的组合列表
    :param topology_type: "star", "chain" 或 "mesh"
    """
    # 1. 结构化解析数据
    if topology_type in ("star", "mesh"):
        record_dict = _parse_star_or_mesh(data, topology_type)
    elif topology_type == "chain":
        record_dict = _parse_chain(data)
    else:
        raise ValueError(f"不支持的拓扑类型: {topology_type}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 2. 动态拼接 SQL 入库
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        columns = ['timestamp'] + list(record_dict.keys())
        placeholders = ', '.join(['?'] * len(columns))
        values = [timestamp] + list(record_dict.values())
        
        sql = f'''
            INSERT INTO test_results ({', '.join(columns)})
            VALUES ({placeholders})
        '''
        cursor.execute(sql, values)
        conn.commit()
        
    print(f" [成功] 实验数据已结构化入库 SQLite (ID: {cursor.lastrowid})")
    return DB_PATH
