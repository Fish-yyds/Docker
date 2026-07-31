"""
交互式菜单与手动测试逻辑模块
"""
from topology import create_topology
from damage import set_damage, check_tc
from test import ping_test, iperf_test
from database import save_result
from plot import generate_plot


def input_damage(link_name):
    """
    获取并校验用户输入的链路损伤参数，增加防崩溃处理
    如果用户直接按回车，默认值为 0；如果输入非数字，捕获异常并返回全 0。
    """
    print(f"\n{'='*27}\n设置链路损伤\n当前链路: {link_name}\n{'='*27}")
    
    try:
        delay = int(input("delay(ms): ") or "0")
        jitter = int(input("jitter(ms): ") or "0")
        loss = float(input("loss(%): ") or "0.0")
        bandwidth = int(input("bandwidth(Mbps): ") or "0")
    except ValueError:
        print("\n 输入格式错误，将默认使用全 0 参数。")
        return 0, 0, 0.0, 0
        
    return delay, jitter, loss, bandwidth


def _execute_and_save(target_ip, topology_type, base_data):
    """
    [内部辅助函数] 统一执行 Ping 和 Iperf 测试，并将数据组装保存
    :param target_ip: 测试的目标 IP 或 容器名
    :param topology_type: "star" 或 "chain"
    :param base_data: 已经组装好的链路配置参数列表
    """
    print("\n 正在执行网络测试，请稍候...")
    avg_rtt, real_loss = ping_test(target_ip)
    throughput = iperf_test(target_ip)
    
    # 将测试结果追加到基础数据后面
    base_data.extend([avg_rtt, real_loss, throughput])
    save_result(base_data, topology_type)
    
    print(f"\n {topology_type} 拓扑测试完成，数据已保存！")


def handle_star_topology():
    """
    处理星型拓扑的交互与测试逻辑
    """
    create_topology("star")
    
    while True:
        print("\n" + "="*27)
        print("星型拓扑链路选择\n")
        print("1. test_a ---> test_b")
        print("2. test_a ---> test_c")
        print("3. 查看 tc 规则")
        print("4. 生成关系图")
        print("0. 返回上级菜单 (重新选择拓扑)")
        print("="*27)
        
        choice = input("选择: ")

        if choice == "0":
            break
        elif choice == "4":
            generate_plot("star")
        elif choice == "3":
            check_tc("test_a", "eth0")
            check_tc("test_a", "eth1")
        elif choice in ("1", "2"):
            # 动态映射目标与网卡，消除重复的 if/else 代码块
            interface = "eth0" if choice == "1" else "eth1"
            target = "test_b" if choice == "1" else "test_c"
            
            # 1. 采集并设置底层损伤
            delay, jitter, loss, bandwidth = input_damage(target)
            set_damage("test_a", interface, delay, jitter, loss, bandwidth)
            
            # 2. 调用公共函数执行测试并保存
            _execute_and_save(
                target_ip=target,
                topology_type="star",
                base_data=[target, delay, jitter, loss, bandwidth]
            )
        else:
            print("\n 错误：无效选项，请重新输入！")


def handle_chain_topology():
    """
    处理链式拓扑的交互与测试逻辑
    """
    create_topology("chain")
    
    while True:
        print("\n" + "="*27)
        print("链式拓扑链路选择\n")
        print("1. test_a ---> test_b ---> test_c")
        print("2. 查看 tc 规则")
        print("3. 生成关系图")
        print("0. 返回上级菜单 (重新选择拓扑)")
        print("="*27)
        
        choice = input("选择: ")

        if choice == "0":
            break
        elif choice == "3":
            generate_plot("chain")
        elif choice == "2":
            check_tc("test_a", "eth0")
            check_tc("test_b", "eth1")
        elif choice == "1":
            # 1. 设置 A-B 链路损伤
            ab_delay, ab_jitter, ab_loss, ab_bandwidth = input_damage("test_a ---> test_b")
            set_damage("test_a", "eth0", ab_delay, ab_jitter, ab_loss, ab_bandwidth)

            # 2. 设置 B-C 链路损伤
            bc_delay, bc_jitter, bc_loss, bc_bandwidth = input_damage("test_b ---> test_c")
            set_damage("test_b", "eth1", bc_delay, bc_jitter, bc_loss, bc_bandwidth)

            # 3. 执行端到端测试并保存 (链式必须使用目标真实 IP: 172.22.0.3)
            _execute_and_save(
                target_ip="172.22.0.3",
                topology_type="chain",
                base_data=[
                    "test_a-->test_b-->test_c",
                    {"AB_delay": ab_delay, "AB_jitter": ab_jitter, "AB_loss": ab_loss, "AB_bandwidth": ab_bandwidth},
                    {"BC_delay": bc_delay, "BC_jitter": bc_jitter, "BC_loss": bc_loss, "BC_bandwidth": bc_bandwidth}
                ]
            )
        else:
            print("\n 错误：无效选项，请重新输入！")


def run_interactive_menu():
    """
    主菜单入口
    """
    while True:
        print("\n" + "="*27)
        print("拓扑选择\n")
        print("1. 星型拓扑")
        print("2. 链式拓扑")
        print("0. 退出程序")
        print("="*27)
        
        topo = input("选择: ")

        if topo == "0":
            print("退出程序...")
            break
        elif topo == "1":
            handle_star_topology()
        elif topo == "2":
            handle_chain_topology()
        else:
            print("\n 错误：无效选项，请重新输入！")
