"""原生 Docker 星型、链式和网状拓扑管理。"""

import shlex
import subprocess
import time
from pathlib import Path

import matplotlib.pyplot as plt

BASE_DIR = Path(__file__).resolve().parent
IMAGE = "ubuntu_net_tools:22.04"

# 原生 Docker 仿真实验使用的容器和网络名称。
NATIVE_CONTAINERS = ("test_a", "test_b", "test_c")
NATIVE_NETWORKS = (
    "net_b", "net_c", "net_ab", "net_bc",
    "net_mesh_ab", "net_mesh_bc", "net_mesh_ac",
)

# 链式跨网桥转发要求宿主机上的三个参数均为 0。
BRIDGE_SETTINGS = (
    "net.bridge.bridge-nf-call-iptables",
    "net.bridge.bridge-nf-call-ip6tables",
    "net.bridge.bridge-nf-call-arptables",
)

# 每项依次包含节点坐标、链路关系和拓扑图标题。
DRAW_SPECS = {
    "star": (
        {"test_b": (-2, 0), "test_a": (0, 0), "test_c": (2, 0)},
        (("test_a", "test_b"), ("test_a", "test_c")),
        "Star Topology",
    ),
    "chain": (
        {"test_a": (-2, 0), "test_b": (0, 0), "test_c": (2, 0)},
        (("test_a", "test_b"), ("test_b", "test_c")),
        "Chain Topology",
    ),
    "mesh": (
        {"test_a": (-1.5, 1), "test_b": (1.5, 1), "test_c": (0, -1)},
        (("test_a", "test_b"), ("test_b", "test_c"), ("test_a", "test_c")),
        "Full-Mesh Topology",
    ),
}


def _run(args, check=True):
    """执行 args 命令；check 为 True 时，命令失败将抛出异常。"""
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "无错误输出"
        raise RuntimeError(f"命令执行失败：{shlex.join(args)}\n{detail}")
    return result


def _docker(*args, check=True):
    """执行 Docker 命令；args 为 Docker 参数，check 控制失败检查。"""
    return _run(["docker", *map(str, args)], check=check)


def _run_container(name, network, ip=None, forward=False):
    """创建容器；name、network 和 ip 指定网络配置，forward 控制 IPv4 转发。"""
    args = ["run", "-dit", "--name", name, "--network", network]
    if ip:
        args += ["--ip", ip]

    # NET_ADMIN 权限用于配置路由、iptables 和 TC。
    args += ["--cap-add", "NET_ADMIN"]
    if forward:
        args += ["--sysctl", "net.ipv4.ip_forward=1"]

    _docker(*args, IMAGE)


def _clear_qdiscs(items):
    """删除 items 中各容器接口的根 TC 规则；接口无规则时忽略错误。"""
    for node, interface in items:
        _docker(
            "exec", node, "tc", "qdisc", "del",
            "dev", interface, "root", check=False,
        )


def _verify_bridge_configuration():
    """检查链式转发依赖的宿主机 bridge netfilter 持久化配置。"""
    invalid = []

    for setting in BRIDGE_SETTINGS:
        result = _run(["sysctl", "-n", setting], check=False)
        value = result.stdout.strip() if not result.returncode else "无法读取"
        if value != "0":
            invalid.append(f"{setting}={value}")

    if invalid:
        raise RuntimeError(
            "宿主机 bridge netfilter 配置未生效：\n  - "
            + "\n  - ".join(invalid)
            + "\n请执行：sudo systemctl restart network-sim-netfilter.service"
        )

    print("[状态] 宿主机 bridge netfilter 配置有效。")


def _create_star():
    """创建 test_a 分别连接 test_b 和 test_c 的星型拓扑。"""
    _docker("network", "create", "net_b")
    _docker("network", "create", "net_c")
    _run_container("test_a", "net_b")
    _run_container("test_b", "net_b")
    _run_container("test_c", "net_c")

    # test_a 同时加入两个网络，作为星型拓扑中心节点。
    _docker("network", "connect", "net_c", "test_a")


def _create_chain():
    """创建 A-B-C 链式拓扑，并配置转发、防火墙及双向静态路由。"""
    _docker(
        "network", "create", "--driver", "bridge",
        "--subnet", "172.21.0.0/16", "net_ab",
    )
    _docker(
        "network", "create", "--driver", "bridge",
        "--subnet", "172.22.0.0/16", "net_bc",
    )

    # test_b 连接两个子网并承担中间路由转发。
    _run_container("test_a", "net_ab", "172.21.0.2")
    _run_container("test_b", "net_ab", "172.21.0.3", forward=True)
    _run_container("test_c", "net_bc", "172.22.0.3")
    _docker("network", "connect", "--ip", "172.22.0.2", "net_bc", "test_b")

    # 放行 test_b 的转发流量并清除可能残留的 TC 规则。
    _docker(
        "exec", "test_b", "sh", "-c",
        "iptables -P FORWARD ACCEPT && iptables -F FORWARD",
    )
    _clear_qdiscs(
        (
            ("test_a", "eth0"),
            ("test_b", "eth0"),
            ("test_b", "eth1"),
            ("test_c", "eth0"),
        )
    )

    # 为 test_a 配置正向路由，为 test_c 配置回程路由。
    _docker(
        "exec", "test_a", "ip", "route", "replace",
        "172.22.0.0/16", "via", "172.21.0.3",
    )
    _docker(
        "exec", "test_c", "ip", "route", "replace",
        "172.21.0.0/16", "via", "172.22.0.2",
    )

    _verify_bridge_configuration()
    _verify_chain_connectivity()


def _verify_chain_connectivity():
    """检查 test_b 转发、双向路由和 test_a 到 test_c 的连通性。"""
    # 每项依次为检查名称、执行命令和预期输出内容。
    checks = (
        (
            "test_b IPv4 转发",
            ["docker", "exec", "test_b", "sysctl", "-n", "net.ipv4.ip_forward"],
            "1",
        ),
        (
            "test_a 静态路由",
            ["docker", "exec", "test_a", "ip", "route", "get", "172.22.0.3"],
            "via 172.21.0.3",
        ),
        (
            "test_c 回程路由",
            ["docker", "exec", "test_c", "ip", "route", "get", "172.21.0.2"],
            "via 172.22.0.2",
        ),
    )

    for label, command, expected in checks:
        output = _run(command).stdout
        if expected not in output:
            raise RuntimeError(f"链式拓扑检查失败：{label}\n{output.strip()}")

    # 从 test_a Ping test_c，验证跨 test_b 的端到端通信。
    ping = _docker(
        "exec", "test_a", "ping", "-n",
        "-c", "3", "-W", "2", "172.22.0.3",
        check=False,
    )
    if not ping.returncode:
        print("[完成] 链式拓扑端到端连通性验证通过。")
        return

    # 失败时收集关键接口、路由和防火墙信息。
    commands = (
        ["docker", "exec", "test_a", "ip", "route"],
        ["docker", "exec", "test_b", "ip", "-br", "addr"],
        ["docker", "exec", "test_b", "ip", "route"],
        ["docker", "exec", "test_b", "iptables", "-nvL", "FORWARD"],
        ["docker", "exec", "test_c", "ip", "route"],
    )
    diagnostics = []

    for command in commands:
        result = _run(command, check=False)
        output = result.stdout.strip() or result.stderr.strip()
        diagnostics.append(f"$ {shlex.join(command)}\n{output}")

    raise RuntimeError(
        "链式拓扑端到端连通性验证失败。\n"
        f"{ping.stdout.strip()}\n\n" + "\n\n".join(diagnostics)
    )


def _create_mesh():
    """创建 A-B、B-C 和 A-C 三条独立网络组成的全网状拓扑。"""
    networks = (
        ("net_mesh_ab", "172.25.0.0/16"),
        ("net_mesh_bc", "172.26.0.0/16"),
        ("net_mesh_ac", "172.27.0.0/16"),
    )
    for name, subnet in networks:
        _docker(
            "network", "create", "--driver", "bridge",
            "--subnet", subnet, name,
        )

    # 首先创建每个容器，再接入对应的第二条链路。
    _run_container("test_a", "net_mesh_ab", "172.25.0.2")
    _run_container("test_b", "net_mesh_ab", "172.25.0.3")
    _run_container("test_c", "net_mesh_bc", "172.26.0.3")
    _docker("network", "connect", "--ip", "172.27.0.2", "net_mesh_ac", "test_a")
    _docker("network", "connect", "--ip", "172.26.0.2", "net_mesh_bc", "test_b")
    _docker("network", "connect", "--ip", "172.27.0.3", "net_mesh_ac", "test_c")

    # 确保新拓扑不继承容器接口上的旧 TC 规则。
    _clear_qdiscs(
        [(node, interface) for node in NATIVE_CONTAINERS for interface in ("eth0", "eth1")]
    )


def generate_topology_image(topology_type):
    """根据 DRAW_SPECS 绘制 topology_type 拓扑图，不参与网络配置。"""
    nodes, links, title = DRAW_SPECS[topology_type]
    output = BASE_DIR / "images" / f"{topology_type}_topology.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(8, 6))

    # 先绘制节点之间的链路，再绘制节点及名称。
    for left, right in links:
        axis.plot(
            [nodes[left][0], nodes[right][0]],
            [nodes[left][1], nodes[right][1]],
            linewidth=2,
            color="#0072B2",
        )

    for name, (x, y) in nodes.items():
        axis.scatter(x, y, s=800, color="#E69F00", zorder=5)
        axis.text(x, y - 0.2, name, ha="center", va="center", fontweight="bold")

    axis.set_title(title)
    axis.axis("off")
    figure.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(figure)
    print(f"[完成] 拓扑图已生成：{output}")


def create_topology(topology_type):
    """清理旧环境并创建 topology_type，可选值为 star、chain 或 mesh。"""
    builders = {
        "star": _create_star,
        "chain": _create_chain,
        "mesh": _create_mesh,
    }
    if topology_type not in builders:
        raise ValueError(f"不支持的拓扑类型：{topology_type}")

    print(f"\n[处理中] 正在创建 {topology_type.upper()} 拓扑...")

    # 清理全部原生实验容器和网络，避免拓扑之间相互影响。
    _docker("rm", "-f", *NATIVE_CONTAINERS, check=False)
    _docker("network", "rm", *NATIVE_NETWORKS, check=False)

    builders[topology_type]()
    time.sleep(1)
    generate_topology_image(topology_type)
    print(f"[完成] {topology_type.upper()} 拓扑已就绪。")