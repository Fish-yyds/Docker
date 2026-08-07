"""在 Docker 容器接口上配置 TBF 与 NetEm。"""

import subprocess

MIN_BURST = 128 * 1024
MAX_BURST = 16 * 1024 * 1024
BURST_WINDOW_MS = 10
TBF_LATENCY_MS = 400
NETEM_LIMIT = 1000


def _docker_exec(node, *command, check=True):
    """在容器中执行命令；关键命令失败时给出完整上下文。"""
    result = subprocess.run(
        ["docker", "exec", node, *map(str, command)],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "无错误输出"
        raise RuntimeError(
            f"容器命令执行失败：{node}\n"
            f"命令：{' '.join(map(str, command))}\n错误：{detail}"
        )
    return result


def _validate(delay, jitter, loss, bandwidth):
    """校验损伤参数，避免将无效值传给 tc。"""
    values = {"delay": delay, "jitter": jitter, "loss": loss, "bandwidth": bandwidth}
    for name, value in values.items():
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"{name} 必须是非负数，当前值：{value!r}")
    if jitter and not delay:
        raise ValueError("配置 jitter 时必须同时设置大于 0 的 delay")
    if loss > 100:
        raise ValueError("loss 不能超过 100%")


def _require_interface(node, interface):
    """确认接口存在，并在失败时列出容器内全部接口。"""
    if not _docker_exec(node, "ip", "link", "show", "dev", interface, check=False).returncode:
        return
    interfaces = _docker_exec(node, "ip", "-br", "link", check=False).stdout.strip()
    raise RuntimeError(f"容器 {node} 不存在接口 {interface}。\n当前接口：\n{interfaces}")


def _burst_bytes(bandwidth):
    """令牌桶至少容纳一个 GSO 报文及约 10 ms 的发送数据。"""
    rate_burst = (bandwidth * 1_000_000 * BURST_WINDOW_MS + 7999) // 8000
    return min(MAX_BURST, max(MIN_BURST, rate_burst))


def set_damage(node, interface, delay=0, jitter=0, loss=0, bandwidth=0):
    """重置接口队列并应用带宽、时延、抖动和丢包配置。"""
    _validate(delay, jitter, loss, bandwidth)
    _require_interface(node, interface)
    print(
        f"[处理中] 应用链路参数：{node}:{interface}，"
        f"delay={delay}ms，jitter={jitter}ms，loss={loss}%，"
        f"bandwidth={bandwidth}Mbps"
    )

    _docker_exec(node, "tc", "qdisc", "del", "dev", interface, "root", check=False)
    netem = ["netem", "limit", NETEM_LIMIT]
    if delay:
        netem += ["delay", f"{delay}ms"]
        if jitter:
            netem.append(f"{jitter}ms")
    if loss:
        netem += ["loss", f"{loss}%"]
    has_netem = bool(delay or loss)

    if bandwidth:
        burst = _burst_bytes(bandwidth)
        _docker_exec(
            node,
            "tc", "qdisc", "add", "dev", interface,
            "root", "handle", "1:", "tbf",
            "rate", f"{bandwidth}mbit",
            "burst", burst,
            "latency", f"{TBF_LATENCY_MS}ms",
        )
        if has_netem:
            _docker_exec(
                node,
                "tc", "qdisc", "add", "dev", interface,
                "parent", "1:1", "handle", "10:", *netem,
            )
        print(f"[完成] 带宽队列已应用：burst={burst} bytes")
    elif has_netem:
        _docker_exec(
            node,
            "tc", "qdisc", "add", "dev", interface,
            "root", "handle", "10:", *netem,
        )
        print("[完成] NetEm 损伤参数已应用。")
    else:
        print("[完成] 旧队列已清除，接口恢复为无附加损伤状态。")


def check_tc(node, interface):
    """打印并返回接口当前队列规则。"""
    _require_interface(node, interface)
    output = _docker_exec(node, "tc", "qdisc", "show", "dev", interface).stdout.strip()
    print(f"\n[状态] {node}:{interface} 队列规则\n{output or '无队列规则'}")
    return output
