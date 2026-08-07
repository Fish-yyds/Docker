FROM ubuntu:22.04

# 预装全部实验工具，避免容器启动后再访问软件源。
RUN sed -i 's/archive.ubuntu.com/mirrors.aliyun.com/g; s/security.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ethtool \
        iperf3 \
        iproute2 \
        iptables \
        iputils-ping \
    && rm -rf /var/lib/apt/lists/*
