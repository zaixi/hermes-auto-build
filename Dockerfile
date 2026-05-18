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

# Shim scripts (placeholder for RTK integration)
COPY shims/ /usr/local/shims/
RUN chmod +x /usr/local/shims/*

# Caveman skill: reduce output token verbosity
COPY skills/ /opt/hermes/skills/
