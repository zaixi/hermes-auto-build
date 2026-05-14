FROM nousresearch/hermes-agent:main

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

# Install feishu dependencies explicitly.
# Upstream moved lark-oapi out of the [all] composite extra to lazy-install,
# but the Feishu adapter checks for it before lazy_deps runs.
# Install here so Feishu works out of the box.
RUN uv pip install --no-cache-dir \
    "lark-oapi==1.5.3" \
    "qrcode==7.4.2"
