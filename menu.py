"""
交互式菜单与手动测试逻辑模块
通过导入 auto_test 模块，实现界面与自动化核心逻辑的分离。
"""
from topology import create_topology
from damage import set_damage, check_tc
from test import ping_test, iperf_test
from database import save_result
from plot import generate_plot

# 核心：导入分离出来的自动化测试工具函数
from auto_test import archive_history_data, run_star_auto_link, run_chain_auto_tests, run_mesh_auto_tests


def input_damage(link_name):
    """获取并校验用户输入的链路损伤参数"""
    print(f"\n{'='*27}\n设置链路损伤\n当前链路: {link_name}\n{'='*27}")
    
    try:
        delay = int(input("delay(ms): ") or "0")
        jitter = int(input("jitter(ms): ") or "0")
        loss = float(input("loss(%): ") or "0.0")
        bandwidth = int(input("bandwidth(Mbps): ") or "0")
    except ValueError:
        print("\n [警告] 输入格式错误，将默认使用全 0 参数。")
        return 0, 0, 0.0, 0
        
    return delay, jitter, loss, bandwidth


def _execute_and_save(target_ip, topology_type, base_data, source="test_a"):
    """统一执行手动 Ping 和 Iperf 测试，并将数据保存"""
    print("\n 正在执行网络测试，请稍候...")
    # 核心修改：将 source 参数传给底层
    avg_rtt, real_loss = ping_test(target_ip, source=source)
    throughput = iperf_test(target_ip, source=source)
    
    base_data.extend([avg_rtt, real_loss, throughput])
    save_result(base_data, topology_type)
    
    print(f"\n [成功] {topology_type} 拓扑测试完成，数据已保存！")

def handle_star_topology():
    """处理星型拓扑的交互与测试逻辑"""
    create_topology("star")
    
    while True:
        print("\n" + "="*35)
        print("星型拓扑链路选择\n")
        print("1. [手动] test_a ---> test_b")
        print("2. [手动] test_a ---> test_c")
        print("3. 查看 tc 规则")
        print("4. 生成关系图")
        print("5. [自动] 执行全矩阵批量测试")
        print("0. 返回上级菜单 (重新选择拓扑)")
        print("="*35)
        
        choice = input("选择: ")

        if choice == "0":
            break
        elif choice == "4":
            generate_plot("star")
        elif choice == "3":
            check_tc("test_a", "eth0")
            check_tc("test_a", "eth1")
        elif choice == "5":
            print("\n [开始] 准备开始自动执行星型拓扑全矩阵测试...")
            archive_history_data("star")
            run_star_auto_link("test_b", "eth0")
            run_star_auto_link("test_c", "eth1")
            print("\n [处理中] 正在生成星型拓扑图表...")
            generate_plot("star")
        elif choice in ("1", "2"):
            interface = "eth0" if choice == "1" else "eth1"
            target = "test_b" if choice == "1" else "test_c"
            
            delay, jitter, loss, bandwidth = input_damage(target)
            set_damage("test_a", interface, delay, jitter, loss, bandwidth)
            
            _execute_and_save(
                target_ip=target,
                topology_type="star",
                base_data=[target, delay, jitter, loss, bandwidth]
            )
        else:
            print("\n [错误] 无效选项，请重新输入！")


def handle_chain_topology():
    """处理链式拓扑的交互与测试逻辑"""
    create_topology("chain")
    
    while True:
        print("\n" + "="*35)
        print("链式拓扑链路选择\n")
        print("1. [手动] test_a ---> test_b ---> test_c")
        print("2. 查看 tc 规则")
        print("3. 生成关系图")
        print("4. [自动] 执行全矩阵批量测试")
        print("0. 返回上级菜单 (重新选择拓扑)")
        print("="*35)
        
        choice = input("选择: ")

        if choice == "0":
            break
        elif choice == "3":
            generate_plot("chain")
        elif choice == "2":
            check_tc("test_a", "eth0")
            check_tc("test_b", "eth1")
        elif choice == "4":
            print("\n [开始] 准备开始自动执行链式拓扑全矩阵测试...")
            archive_history_data("chain")
            run_chain_auto_tests()
            print("\n [处理中] 正在生成链式拓扑图表...")
            generate_plot("chain")
        elif choice == "1":
            ab_delay, ab_jitter, ab_loss, ab_bandwidth = input_damage("test_a ---> test_b")
            set_damage("test_a", "eth0", ab_delay, ab_jitter, ab_loss, ab_bandwidth)

            bc_delay, bc_jitter, bc_loss, bc_bandwidth = input_damage("test_b ---> test_c")
            set_damage("test_b", "eth1", bc_delay, bc_jitter, bc_loss, bc_bandwidth)

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
            print("\n [错误] 无效选项，请重新输入！")


def handle_mesh_topology():
    """处理网状拓扑的交互与测试逻辑"""
    create_topology("mesh")
    
    while True:
        print("\n" + "="*35)
        print("网状拓扑链路选择\n")
        print("1. [手动] test_a <---> test_b")
        print("2. [手动] test_b <---> test_c")
        print("3. [手动] test_a <---> test_c")
        print("4. 查看 tc 规则")
        print("5. 生成关系图")
        print("6. [自动] 执行全矩阵批量测试")
        print("0. 返回上级菜单 (重新选择拓扑)")
        print("="*35)
        
        choice = input("选择: ")

        if choice == "0":
            break
        elif choice == "5":
            generate_plot("mesh")
        elif choice == "4":
            check_tc("test_a", "eth0")
            check_tc("test_a", "eth1")
            check_tc("test_b", "eth1")
        elif choice == "6":
            print("\n [开始] 准备开始自动执行网状拓扑全矩阵测试...")
            archive_history_data("mesh")
            run_mesh_auto_tests()
            print("\n [处理中] 正在生成网状拓扑图表...")
            generate_plot("mesh")
        elif choice in ("1", "2", "3"):
            link_map = {
                "1": ("test_a", "eth0", "172.25.0.3", "test_a<-->test_b"),
                "2": ("test_b", "eth1", "172.26.0.3", "test_b<-->test_c"),
                "3": ("test_a", "eth1", "172.27.0.3", "test_a<-->test_c"),
            }
            sender, interface, target, link_name = link_map[choice]
            
            delay, jitter, loss, bandwidth = input_damage(link_name)
            set_damage(sender, interface, delay, jitter, loss, bandwidth)
            
            _execute_and_save(
                target_ip=target,
                topology_type="mesh",
                base_data=[link_name, delay, jitter, loss, bandwidth],
                source=sender
            )
        else:
            print("\n [错误] 无效选项，请重新输入！")

def run_interactive_menu():
    """主菜单入口"""
    while True:
        print("\n" + "="*35)
        print("通信系统仿真平台 - 拓扑选择\n")
        print("1. 星型拓扑")
        print("2. 链式拓扑")
        print("3. 网状拓扑")
        print("0. 退出程序")
        print("="*35)
        
        topo = input("选择: ")

        if topo == "0":
            print("退出程序...")
            break
        elif topo == "1":
            handle_star_topology()
        elif topo == "2":
            handle_chain_topology()
        elif topo == "3":
            handle_mesh_topology()
        else:
            print("\n [错误] 无效选项，请重新输入！")
