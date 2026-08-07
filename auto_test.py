"""自动化参数矩阵与批量测量。"""

import os
import subprocess
import time
from pathlib import Path

# 每组 Ping 发送 10000 个包，间隔 0.01 秒。
PING_COUNT = 10000
PING_INTERVAL = 0.01

# test.py 在执行测量时读取这两个环境变量。
os.environ["NETWORK_SIM_PING_COUNT"] = str(PING_COUNT)
os.environ["NETWORK_SIM_PING_INTERVAL"] = str(PING_INTERVAL)

from damage import set_damage
from database import save_result
from test import iperf_test, ping_test
from topology import create_topology

BASE_DIR = Path(__file__).resolve().parent
CLAB_FILE = BASE_DIR / "mesh.clab.yml"

# 参数矩阵：5 种时延 × 5 种丢包率，每条链路共 25 组。
BASELINE_BANDWIDTH = 1000
DELAYS = (0, 10, 50, 100, 200)
LOSSES = (0, 1, 3, 5, 10)
REPEATS = max(1, int(os.getenv("NETWORK_SIM_REPEATS", "1")))
CHAIN_SPLIT_RATIO = 0.3

# 每项依次为：链路名称、发送容器、出口接口、目标地址。
DOCKER_MESH_LINKS = (
    ("test_a<-->test_b", "test_a", "eth0", "172.25.0.3"),
    ("test_b<-->test_c", "test_b", "eth1", "172.26.0.3"),
    ("test_a<-->test_c", "test_a", "eth1", "172.27.0.3"),
)
CLAB_MESH_LINKS = (
    ("clab_mesh_a<-->b", "clab-mesh-test_a", "eth1", "172.25.0.3"),
    ("clab_mesh_b<-->c", "clab-mesh-test_b", "eth2", "172.26.0.3"),
    ("clab_mesh_a<-->c", "clab-mesh-test_a", "eth2", "172.27.0.3"),
)
CLAB_CONTAINERS = (
    "clab-mesh-test_a",
    "clab-mesh-test_b",
    "clab-mesh-test_c",
)


def experiment_matrix():
    """根据 DELAYS 和 LOSSES 生成 25 组网络损伤参数。"""
    return [
        {
            "delay": delay,
            "jitter": 0,
            "loss": loss,
            "bandwidth": BASELINE_BANDWIDTH,
        }
        for delay in DELAYS
        for loss in LOSSES
    ]


def _measure(target, source="test_a", attempts=3):
    """从 source 测量 target；attempts 为最大重试次数，返回 RTT、丢包率和吞吐量。"""
    for attempt in range(1, attempts + 1):
        rtt, loss = ping_test(target, source=source)
        if loss >= 100:
            print(f"[重试] 目标不可达：{attempt}/{attempts}")
            continue

        throughput = iperf_test(target, source=source)
        if throughput > 0:
            return rtt, loss, throughput

        print(f"[重试] 吞吐量无效：{attempt}/{attempts}")

    return None


def _progress(name, repeat, index, total):
    """显示链路名称、当前轮次和参数组进度。"""
    print(
        f"\n[批测] {name} | "
        f"轮次 {repeat}/{REPEATS} | 参数组 {index}/{total}"
    )


def _run_link_matrix(links, topology_type, tool_name):
    """遍历 links 参数矩阵，并按拓扑类型和测试工具保存有效结果。"""
    trials = experiment_matrix()

    for link, sender, interface, target in links:
        for repeat in range(1, REPEATS + 1):
            for index, trial in enumerate(trials, 1):
                _progress(link, repeat, index, len(trials))

                # 在发送端出口施加当前参数，再执行 Ping 和 Iperf3。
                set_damage(sender, interface, **trial)
                measured = _measure(target, source=sender)

                if not measured:
                    print(f"[未保存] 参数组测量失败：{trial}")
                    continue

                save_result(
                    [
                        link,
                        trial["delay"],
                        trial["jitter"],
                        trial["loss"],
                        trial["bandwidth"],
                        *measured,
                    ],
                    topology_type,
                    tool_name,
                )
                time.sleep(1)


def run_star_auto_link(target, interface):
    """测试 test_a 到 target 的星型链路；interface 为 test_a 出口接口。"""
    links = ((target, "test_a", interface, target),)
    _run_link_matrix(links, "star", "docker_tc")


def run_mesh_auto_tests():
    """执行原生 Docker 网状拓扑的三条链路。"""
    _run_link_matrix(DOCKER_MESH_LINKS, "mesh", "docker_tc")


def run_clab_mesh_auto_tests():
    """执行 Containerlab 网状拓扑的三条链路。"""
    _run_link_matrix(CLAB_MESH_LINKS, "mesh", "containerlab")


def _split_chain_damage(trial):
    """将 trial 按 3:7 拆分为 A-B 和 B-C 两段链路损伤。"""
    ab_delay = round(trial["delay"] * CHAIN_SPLIT_RATIO, 2)
    ab_loss = round(trial["loss"] * CHAIN_SPLIT_RATIO, 2)

    ab = {
        **trial,
        "delay": ab_delay,
        "loss": ab_loss,
    }
    bc = {
        **trial,
        "delay": round(trial["delay"] - ab_delay, 2),
        "loss": round(trial["loss"] - ab_loss, 2),
        "bandwidth": 0,
    }
    return ab, bc


def run_chain_auto_tests():
    """执行 test_a 经 test_b 到 test_c 的链式端到端参数矩阵。"""
    trials = experiment_matrix()
    link = "test_a-->test_b-->test_c"

    for repeat in range(1, REPEATS + 1):
        for index, trial in enumerate(trials, 1):
            _progress(link, repeat, index, len(trials))
            ab, bc = _split_chain_damage(trial)

            # 两段损伤分别配置在 test_a:eth0 和 test_b:eth1。
            set_damage("test_a", "eth0", **ab)
            set_damage("test_b", "eth1", **bc)
            measured = _measure("172.22.0.3")

            if not measured:
                print(f"[未保存] 链式参数组测量失败：{trial}")
                continue

            save_result(
                [
                    link,
                    {f"AB_{key}": value for key, value in ab.items()},
                    {f"BC_{key}": value for key, value in bc.items()},
                    *measured,
                ],
                "chain",
                "docker_tc",
            )
            time.sleep(1)


def _clab_ready():
    """检查 CLAB_CONTAINERS 中的容器是否全部处于运行状态。"""
    for container in CLAB_CONTAINERS:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode or result.stdout.strip() != "true":
            return False
    return True


def _ensure_clab_deployed():
    """检查 Containerlab；未运行时根据 CLAB_FILE 清理并重新部署。"""
    if _clab_ready():
        print("[状态] Containerlab 环境已经运行。")
        return

    print("[处理中] Containerlab 环境未运行，正在重新部署...")
    topology = str(CLAB_FILE)

    # 清理残留拓扑和同名容器，避免旧接口影响新环境。
    subprocess.run(
        ["sudo", "clab", "destroy", "-t", topology, "--cleanup"],
        check=False,
    )
    subprocess.run(
        ["docker", "rm", "-f", *CLAB_CONTAINERS],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    result = subprocess.run(
        ["sudo", "clab", "deploy", "-t", topology],
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Containerlab 拓扑部署失败")

    # 等待接口初始化并再次验证所有容器状态。
    time.sleep(3)
    if not _clab_ready():
        raise RuntimeError("Containerlab 容器状态验证失败")

    print("[完成] Containerlab 环境部署成功。")


# 创建实验拓扑后，调用对应的自动参数测试函数。

def _run_star_topology():
    """创建 Docker 星型拓扑并测试两条链路。"""
    create_topology("star")
    run_star_auto_link("test_b", "eth0")
    run_star_auto_link("test_c", "eth1")


def _run_chain_topology():
    """创建 Docker 链式拓扑并执行端到端测试。"""
    create_topology("chain")
    run_chain_auto_tests()


def _run_docker_mesh_topology():
    """创建 Docker 网状拓扑并测试全部链路。"""
    create_topology("mesh")
    run_mesh_auto_tests()


def _run_clab_mesh_topology():
    """准备 Containerlab 环境并测试全部网状链路。"""
    _ensure_clab_deployed()
    run_clab_mesh_auto_tests()


def run_all_auto_tests():
    """依次执行全部 Docker 和 Containerlab 拓扑，返回是否全部成功。"""
    stages = (
        ("Docker 星型拓扑", _run_star_topology),
        ("Docker 链式拓扑", _run_chain_topology),
        ("Docker 网状拓扑", _run_docker_mesh_topology),
        ("Containerlab 网状拓扑", _run_clab_mesh_topology),
    )
    failures = []

    print(
        "\n[自动测试] 开始执行全部拓扑\n"
        f"[测试规模] 预计执行 {225 * REPEATS} 组链路测量\n"
        f"[Ping 参数] 数据包={PING_COUNT}，发包间隔={PING_INTERVAL} 秒"
    )

    # 单个拓扑失败时记录原因，但不阻止后续拓扑执行。
    for index, (name, action) in enumerate(stages, 1):
        print(f"\n[拓扑进度] {index}/{len(stages)} | {name}")

        try:
            action()
            print(f"[阶段完成] {name}")
        except Exception as error:
            failures.append((name, error))
            print(f"[阶段失败] {name}：{error}")
            print("[状态] 继续执行下一种拓扑。")

    print(
        f"\n[全部完成] 成功 {len(stages) - len(failures)} 个，"
        f"失败 {len(failures)} 个。"
    )
    for name, error in failures:
        print(f"[失败记录] {name}：{error}")

    return not failures


def main():
    """执行全部拓扑测试，并根据测试结果设置程序退出状态。"""
    raise SystemExit(0 if run_all_auto_tests() else 1)


if __name__ == "__main__":
    main()