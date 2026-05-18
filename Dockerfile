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

# RTK (Rust Token Killer) — CLI output compressor
ARG RTK_VERSION=v0.39.0
RUN curl -fsSL -o /tmp/rtk.deb \
    "https://github.com/rtk-ai/rtk/releases/download/${RTK_VERSION}/rtk_0.39.0-1_amd64.deb" && \
    dpkg -i /tmp/rtk.deb && rm /tmp/rtk.deb

# Shim scripts: intercept CLI commands → route through RTK
COPY shims/ /usr/local/shims/
RUN chmod +x /usr/local/shims/* /usr/local/shims/.rtk-wrapper

# Custom skills — synced to volume by entrypoint's skills_sync.py
COPY skills /opt/hermes/skills/

# Inject shims at front of PATH so agent picks them up first
ENV PATH="/usr/local/shims:${PATH}"
