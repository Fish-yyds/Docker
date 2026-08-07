"""命令行交互入口；负责菜单展示和模块调度，不承载底层测量实现。"""

import subprocess
import time
from pathlib import Path

# 自动测试、网络损伤、数据库、绘图、测量和拓扑模块。
from auto_test import (
    CLAB_MESH_LINKS,
    DOCKER_MESH_LINKS,
    run_chain_auto_tests,
    run_clab_mesh_auto_tests,
    run_mesh_auto_tests,
    run_star_auto_link,
)
from damage import check_tc, set_damage
from database import save_result
from plot import generate_plot
from test import iperf_test, ping_test
from topology import create_topology

BASE_DIR = Path(__file__).resolve().parent
CLAB_TOPOLOGY = BASE_DIR / "mesh.clab.yml"

# Containerlab 各容器必须具备的数据接口及对应地址。
CLAB_REQUIREMENTS = {
    "clab-mesh-test_a": {"eth1": "172.25.0.2/16", "eth2": "172.27.0.2/16"},
    "clab-mesh-test_b": {"eth1": "172.25.0.3/16", "eth2": "172.26.0.2/16"},
    "clab-mesh-test_c": {"eth1": "172.26.0.3/16", "eth2": "172.27.0.3/16"},
}


def _menu(title, items):
    """显示菜单；title 为标题，items 为 (编号, 名称) 序列，返回用户输入。"""
    print(f"\n{'=' * 46}\n{title}\n{'-' * 46}")
    for key, label in items:
        print(f"{key}. {label}")
    print("0. 返回上一级")
    return input("请输入选项编号：").strip()


def _number(prompt, cast, minimum=0, maximum=None):
    """读取数值；cast 指定类型，minimum 和 maximum 限制输入范围。"""
    while True:
        raw = input(prompt).strip() or "0"
        try:
            value = cast(raw)
        except ValueError:
            print("[输入无效] 请输入数字。")
            continue
        if value < minimum or (maximum is not None and value > maximum):
            scope = f"{minimum} 至 {maximum}" if maximum is not None else f"不小于 {minimum}"
            print(f"[输入无效] 数值范围应为{scope}。")
            continue
        return value


def input_damage(link_name):
    """读取 link_name 链路的损伤参数，返回时延、抖动、丢包率和带宽。"""
    print(f"\n[参数配置] {link_name}")
    delay = _number("固定时延 delay (ms)：", int)
    jitter = _number("时延抖动 jitter (ms)：", int)
    loss = _number("随机丢包率 loss (%)：", float, maximum=100)
    bandwidth = _number("带宽上限 bandwidth (Mbps，0 表示不限速)：", int)

    # Netem 不能在没有基础时延的情况下单独设置抖动。
    if jitter and not delay:
        print("[参数调整] jitter 需要非零 delay，本次 jitter 已重置为 0。")
        jitter = 0
    return delay, jitter, loss, bandwidth


def _measure_and_save(target, topology, record, source, tool):
    """从 source 测量 target，并按 topology、record 和 tool 保存有效结果。"""
    print(f"\n[处理中] 开始端到端测量：{source} -> {target}")
    rtt, loss = ping_test(target, source=source)
    if loss >= 100:
        print("[未保存] 目标不可达，本次测量无有效结果。")
        return False

    throughput = iperf_test(target, source=source)
    if throughput <= 0:
        print("[未保存] Iperf3 未返回有效吞吐量。")
        return False

    save_result([*record, rtt, loss, throughput], topology, tool)
    print("[完成] 本次测量及数据保存成功。")
    return True


def _manual_link(link, topology, tool):
    """手动测量单条链路；link 包含名称、发送端、接口、目标和存储名称。"""
    label, sender, interface, target, storage_name = link
    delay, jitter, loss, bandwidth = input_damage(label)

    # 将损伤施加到发送端出口接口，再执行端到端测量。
    set_damage(sender, interface, delay, jitter, loss, bandwidth)
    _measure_and_save(
        target,
        topology,
        [storage_name, delay, jitter, loss, bandwidth],
        sender,
        tool,
    )


def _link_menu(title, topology, links, tc_interfaces, auto_action, tool, comparison=False):
    """通用链路菜单；接收链路、TC 接口、自动测试函数及绘图模式等参数。"""
    link_count = len(links)
    items = [(str(i), f"手动测量：{link[0]}") for i, link in enumerate(links, 1)]
    items += [
        (str(link_count + 1), "查看当前 TC 队列规则"),
        (str(link_count + 2), "根据数据库生成图表"),
        (str(link_count + 3), "执行全部参数矩阵"),
    ]

    while True:
        choice = _menu(title, items)
        if choice == "0":
            return

        if choice.isdigit() and 1 <= int(choice) <= link_count:
            _manual_link(links[int(choice) - 1], topology, tool)
        elif choice == str(link_count + 1):
            for node, interface in tc_interfaces:
                check_tc(node, interface)
        elif choice == str(link_count + 2):
            generate_plot(topology, mode="comparison" if comparison else "single")
        elif choice == str(link_count + 3):
            print("[处理中] 参数矩阵测试开始；仅有效结果会写入数据库。")
            auto_action()
            print("[完成] 参数矩阵测试结束。")
        else:
            print("[输入无效] 请选择菜单中列出的编号。")


def handle_star_topology():
    """创建 Docker 星型拓扑并进入手动、批量、TC 和绘图菜单。"""
    create_topology("star")
    links = (
        ("test_a --> test_b", "test_a", "eth0", "test_b", "test_b"),
        ("test_a --> test_c", "test_a", "eth1", "test_c", "test_c"),
    )

    # 星型批测需要分别测试 test_a 的两个出口。
    def run_all():
        run_star_auto_link("test_b", "eth0")
        run_star_auto_link("test_c", "eth1")

    _link_menu(
        "原生 Docker TC / 星型拓扑",
        "star",
        links,
        (("test_a", "eth0"), ("test_a", "eth1")),
        run_all,
        "docker_tc",
    )


def handle_chain_topology():
    """创建 Docker 链式拓扑并管理端到端手动测量和批量测试。"""
    create_topology("chain")
    items = (
        ("1", "手动测量：test_a --> test_b --> test_c"),
        ("2", "查看当前 TC 队列规则"),
        ("3", "根据数据库生成图表"),
        ("4", "执行全部参数矩阵"),
    )

    while True:
        choice = _menu("原生 Docker TC / 链式拓扑", items)
        if choice == "0":
            return

        if choice == "1":
            # 分别配置 A-B 和 B-C，再测量 A-C 端到端性能。
            ab = input_damage("test_a --> test_b")
            bc = input_damage("test_b --> test_c")
            set_damage("test_a", "eth0", *ab)
            set_damage("test_b", "eth1", *bc)

            # 链式拓扑需要分别保存两段链路的损伤参数。
            ab_record = dict(zip(("AB_delay", "AB_jitter", "AB_loss", "AB_bandwidth"), ab))
            bc_record = dict(zip(("BC_delay", "BC_jitter", "BC_loss", "BC_bandwidth"), bc))
            _measure_and_save(
                "172.22.0.3",
                "chain",
                ["test_a-->test_b-->test_c", ab_record, bc_record],
                "test_a",
                "docker_tc",
            )
        elif choice == "2":
            check_tc("test_a", "eth0")
            check_tc("test_b", "eth1")
        elif choice == "3":
            generate_plot("chain")
        elif choice == "4":
            print("[处理中] 链式参数矩阵测试开始。")
            run_chain_auto_tests()
            print("[完成] 链式参数矩阵测试结束。")
        else:
            print("[输入无效] 请选择菜单中列出的编号。")


def handle_mesh_topology():
    """创建 Docker 网状拓扑，并将链路常量转换为通用菜单格式。"""
    create_topology("mesh")
    links = tuple((*item, item[0]) for item in DOCKER_MESH_LINKS)
    _link_menu(
        "原生 Docker TC / 网状拓扑",
        "mesh",
        links,
        (("test_a", "eth0"), ("test_b", "eth1"), ("test_a", "eth1")),
        run_mesh_auto_tests,
        "docker_tc",
    )


def _clab_status():
    """检查 Containerlab 容器、接口地址和三条数据链路，返回错误列表。"""
    errors = []

    # 首先检查每个容器是否运行，以及接口地址是否符合拓扑定义。
    for container, interfaces in CLAB_REQUIREMENTS.items():
        running = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            check=False,
            capture_output=True,
            text=True,
        )
        if running.returncode or running.stdout.strip() != "true":
            errors.append(f"{container} 未运行")
            continue

        for interface, address in interfaces.items():
            state = subprocess.run(
                ["docker", "exec", container, "ip", "-o", "-4", "addr", "show", "dev", interface],
                check=False,
                capture_output=True,
                text=True,
            )
            if state.returncode or address not in state.stdout:
                errors.append(f"{container}:{interface} 缺少地址 {address}")

    # 容器和接口正常后，再检查 A-B、B-C、A-C 三条数据链路。
    if not errors:
        for source, target, label in (
            ("clab-mesh-test_a", "172.25.0.3", "A-B"),
            ("clab-mesh-test_b", "172.26.0.3", "B-C"),
            ("clab-mesh-test_a", "172.27.0.3", "A-C"),
        ):
            ping = subprocess.run(
                ["docker", "exec", source, "ping", "-n", "-c", "1", "-W", "2", target],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if ping.returncode:
                errors.append(f"数据链路 {label} 不可达")

    return errors


def _ensure_clab_deployed():
    """校验 Containerlab；环境异常时根据 CLAB_TOPOLOGY 清理并重新部署。"""
    errors = _clab_status()
    if not errors:
        print("[状态] Containerlab 容器与数据接口完整。")
        return True

    print("[处理中] Containerlab 环境不完整，准备重新部署：")
    for error in errors:
        print(f"  - {error}")

    # 销毁残留环境和同名容器，避免旧接口影响重新部署。
    topology = str(CLAB_TOPOLOGY)
    subprocess.run(["sudo", "clab", "destroy", "-t", topology, "--cleanup"], check=False)
    subprocess.run(
        ["docker", "rm", "-f", *CLAB_REQUIREMENTS],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if subprocess.run(["sudo", "clab", "deploy", "-t", topology], check=False).returncode:
        print("[失败] Containerlab 部署命令执行失败。")
        return False

    # 等待接口初始化完成，然后重新执行完整状态检查。
    time.sleep(2)
    errors = _clab_status()
    if errors:
        print("[失败] 部署完成但环境校验未通过：")
        for error in errors:
            print(f"  - {error}")
        return False

    print("[完成] Containerlab 环境部署并校验成功。")
    return True


def handle_clab_mesh_topology():
    """准备 Containerlab 环境并进入网状拓扑操作菜单。"""
    if not _ensure_clab_deployed():
        return

    links = tuple((*item, item[0]) for item in CLAB_MESH_LINKS)
    _link_menu(
        "Containerlab / 网状拓扑",
        "mesh",
        links,
        (
            ("clab-mesh-test_a", "eth1"),
            ("clab-mesh-test_b", "eth2"),
            ("clab-mesh-test_a", "eth2"),
        ),
        run_clab_mesh_auto_tests,
        "containerlab",
        comparison=True,
    )


def handle_docker_tc_menu():
    """显示 Docker TC 拓扑菜单，并调用选中拓扑对应的处理函数。"""
    handlers = {
        "1": handle_star_topology,
        "2": handle_chain_topology,
        "3": handle_mesh_topology,
    }
    items = (("1", "星型拓扑"), ("2", "链式拓扑"), ("3", "网状拓扑"))

    while True:
        choice = _menu("原生 Docker TC / 拓扑选择", items)
        if choice == "0":
            return

        handler = handlers.get(choice)
        if handler:
            handler()
        else:
            print("[输入无效] 请选择菜单中列出的编号。")


def run_interactive_menu():
    """程序主交互入口；调度 Docker TC 或 Containerlab 仿真模块。"""
    handlers = {
        "1": handle_docker_tc_menu,
        "2": handle_clab_mesh_topology,
    }
    items = (
        ("1", "原生 Docker TC 仿真"),
        ("2", "Containerlab 网状拓扑仿真"),
    )

    while True:
        choice = _menu("通信系统网络仿真平台", items)
        if choice == "0":
            print("[完成] 程序已退出。")
            return

        handler = handlers.get(choice)
        if handler:
            handler()
        else:
            print("[输入无效] 请选择菜单中列出的编号。")