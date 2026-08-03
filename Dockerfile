ARG BASE_TAG=latest
FROM nousresearch/hermes-agent:${BASE_TAG}

# Ensure venv bin is on PATH for all processes (gateway, terminal, sandbox)
ENV PATH="/opt/hermes/.venv/bin:${PATH}"

# Ensure .venv/bin survives login shell (used by terminal tool's env snapshot)
# Login shells source /etc/profile which resets PATH to system defaults.
# /etc/profile.d/*.sh is the standard Debian mechanism to extend login PATH.
RUN mkdir -p /etc/profile.d && \
    echo 'export PATH="/opt/hermes/.venv/bin:$PATH"' > /etc/profile.d/hermes-path.sh

# Install additional apt packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        jq \
        unzip \
        diffutils \
        socat \
        zip \
        chromium && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install shellcheck (for bash-language-server LSP diagnostics)
RUN curl -fsSL \
    https://github.com/koalaman/shellcheck/releases/download/v0.10.0/shellcheck-v0.10.0.linux.x86_64.tar.xz \
    | tar xJ -C /usr/local/bin --strip-components=1 \
        shellcheck-v0.10.0/shellcheck && \
    chmod +x /usr/local/bin/shellcheck

# Install feishu, hindsight, and rtk-hermes plugin dependencies.
# NOTE: lark-oapi is intentionally NOT pinned here — the official image
# lazy-installs it at first use (tools/lazy_deps.py: platform.feishu →
# lark-oapi==1.6.8). Pre-installing an older version here short-circuits
# that mechanism (FEISHU_AVAILABLE=True → version check never runs) and
# breaks the WS client (extra_ua_tags param requires lark-oapi>=1.6.x).
RUN uv pip install --no-cache-dir \
    "qrcode==7.4.2" \
    "hindsight-client" \
    "rtk-hermes" \
    "aiohttp" \
    "httpx"

# RTK (Rust Token Killer) — CLI output compressor, auto-latest
ENV RTK_INSTALL_DIR=/usr/local/bin
RUN curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh

# agent-browser (browser_navigate) + Chromium, and Lark/Feishu CLI
RUN npm install -g agent-browser @larksuite/cli && \
    agent-browser install --with-deps && \
    rm -rf /tmp/* /root/.npm /root/.cache /tmp/.npm

# Custom skills — synced to volume by entrypoint's skills_sync.py
COPY skills /opt/hermes/skills/
