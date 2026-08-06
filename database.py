"""使用 SQLite 结构化存储测试测量数据。"""

import sqlite3
import inspect
import time
from datetime import datetime
from pathlib import Path

# ==================================
# 全局路径与数据库配置
# ==================================
DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "simulation_results.db"


def _connect():
    """创建带并发等待策略的 SQLite 连接。"""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def init_db():
    """初始化 SQLite 数据库，自动建表"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        cursor = conn.cursor()
        # 创建统一的数据总表，利用可空字段兼容不同的拓扑参数
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                tool_name TEXT NOT NULL,
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
    """返回数据库路径"""
    return DB_PATH

# ==================================
# 数据解析辅助函数 (已恢复完整逻辑)
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
# 核心保存逻辑 (支持全自动识别)
# ==================================
def save_result(data, topology_type):
    """
    将单次测量记录直接插入到 SQLite 数据库中。
    内置智能探测：自动识别工具类型，无需手动传参。
    """
    tool_name = "docker_tc"
    
    # 1. 优先通过链路名称特征识别
    link_str = str(data[0]).lower()
    if "clab" in link_str or "containerlab" in link_str:
        tool_name = "containerlab"
    else:
        # 2. 如果链路名没特征，反向侦测调用堆栈
        try:
            caller_name = inspect.stack()[1].function.lower()
            if "clab" in caller_name or "containerlab" in caller_name:
                tool_name = "containerlab"
        except Exception:
            pass

    # 3. 结构化解析数据
    if topology_type in ("star", "mesh"):
        record_dict = _parse_star_or_mesh(data, topology_type)
    elif topology_type == "chain":
        record_dict = _parse_chain(data)
    else:
        raise ValueError(f"不支持的拓扑类型: {topology_type}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    columns = ['timestamp', 'tool_name'] + list(record_dict.keys())
    placeholders = ', '.join(['?'] * len(columns))
    values = [timestamp, tool_name] + list(record_dict.values())
    sql = f'''
        INSERT INTO test_results ({', '.join(columns)})
        VALUES ({placeholders})
    '''

    lastrowid = None
    for attempt in range(1, 4):
        try:
            with _connect() as conn:
                cursor = conn.execute(sql, values)
                conn.commit()
                lastrowid = cursor.lastrowid
            break
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 3:
                raise
            time.sleep(0.5 * attempt)
        
    print(f" [成功] 数据入库 SQLite (工具: {tool_name}, ID: {lastrowid})")
    return DB_PATH

