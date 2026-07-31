"""
通信系统仿真平台 - 主程序入口
"""
from menu import run_interactive_menu

def main():
    try:
        # 启动交互式命令行菜单
        run_interactive_menu()
    except KeyboardInterrupt:
        print("\n\n检测到强制中断 (Ctrl+C)，程序已安全退出。")

if __name__ == "__main__":
    main()
