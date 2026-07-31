FROM ubuntu:22.04

# 替换为阿里云源加速
RUN sed -i 's/archive.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    sed -i 's/security.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    sed -i 's/ports.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list

# 更新并安装所有必需工具
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    iproute2 \
    iputils-ping \
    iperf3 \
    iptables \
    && rm -rf /var/lib/apt/lists/*
