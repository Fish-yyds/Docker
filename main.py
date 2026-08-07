"""通信系统仿真平台入口。"""

from menu import run_interactive_menu


def main():
    try:
        run_interactive_menu()
    except KeyboardInterrupt:
        print("\n[中止] 用户终止了当前操作。")
    except (RuntimeError, ValueError) as exc:
        print(f"\n[失败] {exc}")
    except FileNotFoundError as exc:
        print(f"\n[失败] 缺少系统命令：{exc.filename}")


if __name__ == "__main__":
    main()
