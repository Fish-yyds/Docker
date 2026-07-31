"""在 Docker 容器内配置 Linux 流量控制规则。"""

import subprocess


def _docker_exec(node, *command, check=True):
    """
    在指定的 Docker 容器中执行命令。
    
    :param node: 容器名称。
    :param command: 要执行的命令参数。
    :param check: 为 True 时，如果命令执行失败则抛出 RuntimeError 异常。
    :return: subprocess.CompletedProcess 实例。
    """
    result = subprocess.run(
        ["docker", "exec", node, *map(str, command)],
        check=False,
        capture_output=True,
        text=True,
    )
    
    if check and result.returncode != 0:
        error_message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"容器 {node} 命令执行失败: {error_message}")
        
    return result


def set_damage(node, interface, delay=0, jitter=0, loss=0, bandwidth=0):
    """
    在容器的网络接口上配置网络损伤（时延、抖动、丢包、带宽限制）。
    """
    # 参数合法性校验
    if min(delay, jitter, loss, bandwidth) < 0:
        raise ValueError("损伤参数不能小于 0")
    if jitter > 0 and delay <= 0:
        raise ValueError("配置抖动时必须同时配置大于 0 的时延")

    print(
        f" [处理中] 配置网络损伤: {node}:{interface}, "
        f"delay={delay}ms, jitter={jitter}ms, loss={loss}%, bandwidth={bandwidth}Mbps"
    )

    # 清除已有的 tc 规则（如果不存在规则，则忽略错误）
    _docker_exec(node, "tc", "qdisc", "del", "dev", interface, "root", check=False)

    # 构建 netem 损伤参数
    netem_args = ["netem", "limit", "1000"]
    has_netem_damage = False

    if delay > 0:
        netem_args.extend(["delay", f"{delay}ms"])
        if jitter > 0:
            netem_args.append(f"{jitter}ms")
        has_netem_damage = True
        
    if loss > 0:
        netem_args.extend(["loss", f"{loss}%"])
        has_netem_damage = True

    # 根据是否限制带宽和损伤参数，决定执行的 tc 命令序列
    if bandwidth > 0:
        # 1. 限制带宽：使用 TBF (Token Bucket Filter) 算法配置 root 节点
        # 【核心修复】：将 burst 从 32kbit 提升至 1m，防止高带宽(如 500M/1000M)下的微突发引发异常丢包
        _docker_exec(
            node, "tc", "qdisc", "add", "dev", interface,
            "root", "handle", "1:", "tbf", "rate", f"{bandwidth}mbit",
            "burst", "1m", "latency", "400ms",
        )
        
        # 2. 如果存在其他损伤，将其串联在 TBF 的子节点下
        if has_netem_damage:
            _docker_exec(
                node, "tc", "qdisc", "add", "dev", interface,
                "parent", "1:1", "handle", "10:", *netem_args,
            )
    elif has_netem_damage:
        # 仅配置网络损伤，无需限速时，直接挂载到 root 节点
        _docker_exec(
            node, "tc", "qdisc", "add", "dev", interface,
            "root", "handle", "10:", *netem_args,
        )


def check_tc(node, interface):
    """
    查看并打印指定容器网卡的 tc 规则配置。
    """
    result = _docker_exec(node, "tc", "qdisc", "show", "dev", interface)
    print(f"\n [信息] {node}:{interface} 当前 tc 规则:\n{result.stdout}")
    return result.stdout
