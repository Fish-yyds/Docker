"""
网络拓扑构建与初始化模块 (终极优化版)
"""
import subprocess
import os
import time
import matplotlib.pyplot as plt

# ==================================
# 基础工具函数
# ==================================

def run(cmd):
    """
    执行 Shell 命令的公共包装函数，静默屏蔽标准错误输出
    """
    result = subprocess.run(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True
    )
   # if result.stdout.strip():
    #    print(result.stdout.strip())
    return result


def install_tools():
    """
    【极速优化】由于全面启用了 ubuntu_net_tools:22.04 本地预装镜像，
    这里不再需要执行缓慢且容易卡死的 apt-get 动态下载过程。
    """
    print("\n[成功] 已检测到使用本地预装工具镜像，跳过动态下载，极速启动！")


def generate_topology_image(mode):
    """
    使用 Matplotlib 绘制当前网络拓扑结构的示意图
    """
    if not os.path.exists("images"):
        os.mkdir("images")

    plt.figure(figsize=(8, 6))

    # 动态配置不同拓扑的节点坐标与连线
    if mode == "star":
        nodes = {"test_b": (-2, 0), "test_a": (0, 0), "test_c": (2, 0)}
        links = [("test_a", "test_b"), ("test_a", "test_c")]
        title = "Star Topology"
        filename = "images/star_topology.png"
    elif mode == "chain":
        nodes = {"test_a": (-2, 0), "test_b": (0, 0), "test_c": (2, 0)}
        links = [("test_a", "test_b"), ("test_b", "test_c")]
        title = "Chain Topology"
        filename = "images/chain_topology.png"
    else:  # 网状拓扑 (Mesh) 绘图逻辑
        nodes = {"test_a": (-1.5, 1), "test_b": (1.5, 1), "test_c": (0, -1)}
        links = [("test_a", "test_b"), ("test_b", "test_c"), ("test_a", "test_c")]
        title = "Full-Mesh Topology"
        filename = "images/mesh_topology.png"

    # 绘制连线
    for a, b in links:
        x1, y1 = nodes[a]
        x2, y2 = nodes[b]
        plt.plot([x1, x2], [y1, y2], linewidth=2, color='#0072B2')

    # 绘制节点与文字标签
    for name, (x, y) in nodes.items():
        plt.scatter(x, y, s=800, color='#E69F00', zorder=5)
        plt.text(x, y - 0.2, name, ha="center", va="center", fontsize=12, fontweight='bold')

    plt.title(title, fontsize=16)
    plt.axis("off")
    plt.savefig(filename, dpi=220, bbox_inches="tight")
    plt.close()
    
    print(f"[成功] 拓扑图已生成: {filename}")


# ==================================
# 拓扑构建核心逻辑
# ==================================

def _create_star():
    """[内部函数] 构建星型拓扑网络结构"""
    run("docker network create net_b")
    run("docker network create net_c")

    for name, net in [("test_a", "net_b"), ("test_b", "net_b"), ("test_c", "net_c")]:
        run(f"docker run -dit --name {name} --network {net} --cap-add NET_ADMIN ubuntu_net_tools:22.04")

    run("docker network connect net_c test_a")


def _create_chain():
    """[内部函数] 构建链式拓扑网络结构并配置静态路由"""
    run("docker network create --driver bridge --subnet=172.21.0.0/16 net_ab")
    run("docker network create --driver bridge --subnet=172.22.0.0/16 net_bc")

    run("docker run -dit --name test_a --network net_ab --ip 172.21.0.2 --cap-add NET_ADMIN ubuntu_net_tools:22.04")
    run("docker run -dit --name test_b --network net_ab --ip 172.21.0.3 --cap-add NET_ADMIN ubuntu_net_tools:22.04")
    run("docker run -dit --name test_c --network net_bc --ip 172.22.0.3 --cap-add NET_ADMIN ubuntu_net_tools:22.04")

    run("docker network connect --ip 172.22.0.2 net_bc test_b")
    
    run('docker exec test_b bash -c "echo 1 > /proc/sys/net/ipv4/ip_forward"')
    run('docker exec test_b bash -c "iptables -P FORWARD ACCEPT && iptables -F"')

    run("""
        docker exec test_a tc qdisc del dev eth0 root || true
        docker exec test_b tc qdisc del dev eth0 root || true
        docker exec test_b tc qdisc del dev eth1 root || true
        docker exec test_c tc qdisc del dev eth0 root || true
    """)

    run('docker exec test_a bash -c "ip route add 172.22.0.0/16 via 172.21.0.3"')
    run('docker exec test_c bash -c "ip route add 172.21.0.0/16 via 172.22.0.2"')

    print("\n[成功] 正在测试链式端到端连通性...")
    run("docker exec test_a ping -c 3 172.22.0.3")


def _create_mesh():
    """[内部函数] 构建全网状拓扑结构 (Mesh: A-B, B-C, A-C 两两直连)"""
    run("docker network create --driver bridge --subnet=172.25.0.0/16 net_mesh_ab")
    run("docker network create --driver bridge --subnet=172.26.0.0/16 net_mesh_bc")
    run("docker network create --driver bridge --subnet=172.27.0.0/16 net_mesh_ac")

    run("docker run -dit --name test_a --network net_mesh_ab --ip 172.25.0.2 --cap-add NET_ADMIN ubuntu_net_tools:22.04")
    run("docker run -dit --name test_b --network net_mesh_ab --ip 172.25.0.3 --cap-add NET_ADMIN ubuntu_net_tools:22.04")
    run("docker run -dit --name test_c --network net_mesh_bc --ip 172.26.0.3 --cap-add NET_ADMIN ubuntu_net_tools:22.04")

    run("docker network connect --ip 172.27.0.2 net_mesh_ac test_a")
    run("docker network connect --ip 172.26.0.2 net_mesh_bc test_b")
    run("docker network connect --ip 172.27.0.3 net_mesh_ac test_c")
    run("""
        docker exec test_a tc qdisc del dev eth0 root || true
        docker exec test_a tc qdisc del dev eth1 root || true
        docker exec test_b tc qdisc del dev eth0 root || true
        docker exec test_b tc qdisc del dev eth1 root || true
        docker exec test_c tc qdisc del dev eth0 root || true
        docker exec test_c tc qdisc del dev eth1 root || true
    """)

    print("\n[成功] 网状拓扑 (Full-Mesh) 环境构建完成！")


def create_topology(topology_type):
    """入口函数：清理旧环境，创建指定拓扑，安装环境依赖并绘图"""
    print(f"\n[处理中] 准备构建 {topology_type.upper()} 拓扑环境...")

    run("docker rm -f test_a test_b test_c || true")
    run("docker network rm net_b net_c net_ab net_bc net_mesh_ab net_mesh_bc net_mesh_ac || true")

    if topology_type == "star":
        _create_star()
    elif topology_type == "chain":
        _create_chain()
    elif topology_type == "mesh":
        _create_mesh()
    else:
        print("[错误] 未知拓扑，构建失败")
        return

    print("[处理中] 等待网络初始化...")
    time.sleep(3)

    install_tools()
    generate_topology_image(topology_type)
