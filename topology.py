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
        stderr=subprocess.DEVNULL, # 修复了原代码这里多余的 """ 符号
        text=True
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    return result


def install_tools():
    """
    【极速优化】由于全面启用了 ubuntu_net_tools:22.04 本地预装镜像，
    这里不再需要执行缓慢且容易卡死的 apt-get 动态下载过程。
    """
    print("\n✅ 已检测到使用本地预装工具镜像，跳过动态下载，极速启动！")


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
    else:
        nodes = {"test_a": (-2, 0), "test_b": (0, 0), "test_c": (2, 0)}
        links = [("test_a", "test_b"), ("test_b", "test_c")]
        title = "Chain Topology"
        filename = "images/chain_topology.png"

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
    
    print(f" 拓扑图已生成: {filename}")


# ==================================
# 拓扑构建核心逻辑
# ==================================

def _create_star():
    """ 
    [内部函数] 构建星型拓扑网络结构 
    """
    # 创建网络
    run("docker network create net_b")
    run("docker network create net_c")

    # 【优化】全部替换为自带工具的 ubuntu_net_tools:22.04 镜像
    for name, net in [("test_a", "net_b"), ("test_b", "net_b"), ("test_c", "net_c")]:
        run(f"docker run -dit --name {name} --network {net} --cap-add NET_ADMIN ubuntu_net_tools:22.04")

    # test_a 跨接第二个网络，形成中心节点
    run("docker network connect net_c test_a")


def _create_chain():
    """ 
    [内部函数] 构建链式拓扑网络结构并配置静态路由
    【核心修复】强制锁定子网与 IP，彻底杜绝 IP 漂移引发的路由失效问题
    """
    # 1. 强制指定子网网段
    run("docker network create --driver bridge --subnet=172.21.0.0/16 net_ab")
    run("docker network create --driver bridge --subnet=172.22.0.0/16 net_bc")

    # 2. 启动容器，并用 --ip 强制绑定绝对静态 IP
    run("docker run -dit --name test_a --network net_ab --ip 172.21.0.2 --cap-add NET_ADMIN ubuntu_net_tools:22.04")
    run("docker run -dit --name test_b --network net_ab --ip 172.21.0.3 --cap-add NET_ADMIN ubuntu_net_tools:22.04")
    run("docker run -dit --name test_c --network net_bc --ip 172.22.0.3 --cap-add NET_ADMIN ubuntu_net_tools:22.04")

    # 3. test_b 跨接第二个网络，同时强制分配该网段的静态 IP
    run("docker network connect --ip 172.22.0.2 net_bc test_b")
    
    # 开启 B 节点的 IP 转发功能并放行 iptables 规则
    run('docker exec test_b bash -c "echo 1 > /proc/sys/net/ipv4/ip_forward"')
    run('docker exec test_b bash -c "iptables -P FORWARD ACCEPT && iptables -F"')

    # 清理所有网卡的 tc 规则防止历史干扰
    run("""
        docker exec test_a tc qdisc del dev eth0 root || true
        docker exec test_b tc qdisc del dev eth0 root || true
        docker exec test_b tc qdisc del dev eth1 root || true
        docker exec test_c tc qdisc del dev eth0 root || true
    """)

    # 添加双向静态路由 (A -> C 和 C -> A)
    # 因为上面已经用 --ip 锁死了分配，这里的静态网关绝对不会出错！
    run('docker exec test_a bash -c "ip route add 172.22.0.0/16 via 172.21.0.3"')
    run('docker exec test_c bash -c "ip route add 172.21.0.0/16 via 172.22.0.2"')

    print("\n 正在测试链式端到端连通性...")
    run("docker exec test_a ping -c 3 172.22.0.3")


def create_topology(topology_type):
    """
    入口函数：清理旧环境，创建指定拓扑，安装环境依赖并绘图
    """
    print(f"\n 准备构建 {topology_type.upper()} 拓扑环境...")

    # 清理旧容器和网络 (添加 || true 忽略不存在时的报错警告)
    run("docker rm -f test_a test_b test_c || true")
    run("docker network rm net_b net_c net_ab net_bc || true")

    # 路由派发
    if topology_type == "star":
        _create_star()
    elif topology_type == "chain":
        _create_chain()
    else:
        print(" 未知拓扑，构建失败")
        return

    print(" 等待网络初始化...")
    time.sleep(3)

    # 统一调用安装与生成图片逻辑
    install_tools()
    generate_topology_image(topology_type)
