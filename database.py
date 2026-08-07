"""SQLite 测量结果存储。"""

import sqlite3
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "simulation_results.db"
VALID_TOOLS = {"docker_tc", "containerlab"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    topology_type TEXT NOT NULL,
    link_name TEXT NOT NULL,
    delay REAL, jitter REAL, loss REAL, bandwidth REAL,
    ab_delay REAL, ab_jitter REAL, ab_loss REAL, ab_bandwidth REAL,
    bc_delay REAL, bc_jitter REAL, bc_loss REAL, bc_bandwidth REAL,
    avg_rtt REAL, real_loss REAL, throughput REAL
)
"""


def _connect():
    """创建支持并发等待的数据库连接。"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db():
    """创建数据目录、结果表和常用查询索引。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute(SCHEMA)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_results_lookup "
            "ON test_results(topology_type, tool_name, link_name)"
        )


def result_path(_topology_type=None):
    """返回结果数据库的绝对路径。"""
    return DB_PATH


def _parse_record(data, topology_type):
    """将各拓扑的列表数据转换为数据库字段。"""
    if topology_type in {"star", "mesh"}:
        link, delay, jitter, loss, bandwidth, rtt, real_loss, throughput = data
        if topology_type == "star" and link in {"test_b", "test_c"}:
            link = f"test_a-->{link}"
        return {
            "topology_type": topology_type,
            "link_name": link,
            "delay": delay,
            "jitter": jitter,
            "loss": loss,
            "bandwidth": bandwidth,
            "avg_rtt": rtt,
            "real_loss": real_loss,
            "throughput": throughput,
        }

    if topology_type == "chain":
        link, ab, bc, rtt, real_loss, throughput = data
        record = {
            "topology_type": "chain",
            "link_name": link,
            "avg_rtt": rtt,
            "real_loss": real_loss,
            "throughput": throughput,
        }
        for prefix, values in (("ab", ab), ("bc", bc)):
            record.update(
                {
                    f"{prefix}_delay": values[f"{prefix.upper()}_delay"],
                    f"{prefix}_jitter": values[f"{prefix.upper()}_jitter"],
                    f"{prefix}_loss": values[f"{prefix.upper()}_loss"],
                    f"{prefix}_bandwidth": values[f"{prefix.upper()}_bandwidth"],
                }
            )
        return record

    raise ValueError(f"不支持的拓扑类型：{topology_type}")


def save_result(data, topology_type, tool_name="docker_tc"):
    """保存一条有效测量结果，并返回数据库路径。"""
    if tool_name not in VALID_TOOLS:
        raise ValueError(f"不支持的仿真工具：{tool_name}")

    record = _parse_record(data, topology_type)
    columns = ["timestamp", "tool_name", *record]
    values = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        tool_name,
        *record.values(),
    ]
    sql = (
        f"INSERT INTO test_results ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)})"
    )

    for attempt in range(3):
        try:
            with _connect() as conn:
                row_id = conn.execute(sql, values).lastrowid
            print(f"[完成] 测量结果已保存：工具={tool_name}，ID={row_id}")
            return DB_PATH
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))


init_db()
