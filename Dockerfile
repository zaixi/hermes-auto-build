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

# Install shellcheck (for bash-language-server LSP diagnostics)
RUN curl -fsSL \
    https://github.com/koalaman/shellcheck/releases/download/v0.10.0/shellcheck-v0.10.0.linux.x86_64.tar.xz \
    | tar xJ -C /usr/local/bin --strip-components=1 \
        shellcheck-v0.10.0/shellcheck && \
    chmod +x /usr/local/bin/shellcheck

# Install feishu, hindsight, and rtk-hermes plugin dependencies
RUN uv pip install --no-cache-dir \
    "lark-oapi==1.5.3" \
    "qrcode==7.4.2" \
    "hindsight-client" \
    "rtk-hermes" \
    "aiohttp" \
    "httpx"

# RTK (Rust Token Killer) — CLI output compressor, auto-latest
ENV RTK_INSTALL_DIR=/usr/local/bin
RUN curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh

# Custom skills — synced to volume by entrypoint's skills_sync.py
COPY skills /opt/hermes/skills/
