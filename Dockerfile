FROM nousresearch/hermes-agent:latest

# Install additional apt packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        jq \
        unzip \
        diffutils \
        socat \
        zip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install feishu and hindsight dependencies
RUN uv pip install --no-cache-dir \
    "lark-oapi==1.5.3" \
    "qrcode==7.4.2" \
    "hindsight-client"

# Install RTK (Rust Token Killer) — CLI output compressor
ARG RTK_VERSION=v0.39.0
RUN curl -fsSL \
    "https://github.com/rtk-ai/rtk/releases/download/${RTK_VERSION}/rtk-x86_64-unknown-linux-musl.tar.gz" \
    | tar xz -C /usr/local/bin && chmod +x /usr/local/bin/rtk

# Shim scripts: intercept common CLI commands → route through RTK
COPY shims/ /usr/local/shims/
RUN chmod +x /usr/local/shims/*

# Caveman skill: reduce output token verbosity
COPY skills/ /opt/hermes/skills/

# Inject shims at front of PATH (before /usr/bin) so agent picks them up first
ENV PATH="/usr/local/shims:${PATH}"
