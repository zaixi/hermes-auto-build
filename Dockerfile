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
# file: agent 识别文件类型（whp 2026-08-21 曾因缺 file 报 command not found）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        jq \
        unzip \
        diffutils \
        file \
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

# Install feishu, tts, silk-stt and hindsight dependencies.
# lark-oapi / edge-tts / pilk are pinned to the EXACT versions
# tools/lazy_deps.py allowlists (platform.feishu → lark-oapi==1.6.8,
# tts.edge → edge-tts==7.2.7, stt.silk → pilk==0.2.4), so the runtime lazy
# installer no-ops: lazy_deps.ensure() returns early once _is_satisfied()
# sees an installed version inside the pinned range.
# Baking matters because /opt/data is an ANONYMOUS docker volume — the
# lazy-packages store it holds is discarded with the old container on every
# redeploy, so an unbaked package is re-downloaded on each image update
# (observed 5-8 lazy-install events per profile per week, 13-94s each).
# pilk ships no manylinux wheel (Windows wheels + sdist only), so it is built
# from source here; the base image carries gcc and Python.h
# (/usr/include/python3.13, venv python is /usr/bin/python3.13).
# Do NOT pin lark-oapi below 1.6.x: the feishu adapter passes extra_ua_tags to
# the lark WS client and an older SDK raises TypeError (last seen 2026-08-03);
# 1.6.8 is what this instance actually runs and is verified working.
# pandas + openpyxl: whp profile financial work (salary allocation / expense
# reports / monthly reports). Pinned to avoid silent upstream breakage.
# hermes-keenable-web: Keenable search+extract provider (replaces tavily,
# removed upstream in v0.21. KEENABLE_API_KEY in .env, 100K free req/mo).
# 2026-09-04 extract backend switched from tavily -> keenable.
RUN uv pip install --no-cache-dir \
    "qrcode==7.4.2" \
    "hindsight-client" \
    "aiohttp" \
    "httpx" \
    "pandas==3.0.5" \
    "openpyxl==3.1.5" \
    "hermes-keenable-web==0.1.1" \
    "lark-oapi==1.6.8" \
    "edge-tts==7.2.7" \
    "pilk==0.2.4"

# agent-browser (browser_navigate) + Chromium, and Lark/Feishu CLI
# npm 11+ blocks postinstall scripts by default — allow them explicitly.
# Chrome system deps are already covered by the chromium apt package above,
# so --with-deps (which needs sudo, absent in base image) is unnecessary.
RUN npm install -g --allow-scripts=@larksuite/cli,agent-browser agent-browser @larksuite/cli && \
    agent-browser install && \
    rm -rf /tmp/* /root/.npm /root/.cache /tmp/.npm

# Backport upstream #62930 / #86417: a normal availability gate returning
# False means an optional capability is off, not that its probe crashed.
# Keep exceptions and recent-success flakes at WARNING; move steady-state
# False verdicts to DEBUG so they do not flood Docker warning logs.
COPY patches/apply_check_fn_false_debug.py /tmp/apply_check_fn_false_debug.py
COPY tests/test_check_fn_false_log_level.py /tmp/test_check_fn_false_log_level.py
RUN if HERMES_SOURCE_ROOT=/opt/hermes \
        /opt/hermes/.venv/bin/python /tmp/test_check_fn_false_log_level.py >/tmp/check-fn-preflight.log 2>&1; then \
        echo 'check_fn False log-level behavior already fixed upstream; skipping hotfix'; \
    else \
        /opt/hermes/.venv/bin/python /tmp/apply_check_fn_false_debug.py \
            /opt/hermes/tools/registry.py; \
    fi && \
    /opt/hermes/.venv/bin/python -m py_compile \
        /opt/hermes/tools/registry.py && \
    HERMES_SOURCE_ROOT=/opt/hermes \
        /opt/hermes/.venv/bin/python /tmp/test_check_fn_false_log_level.py && \
    rm -f \
        /tmp/apply_check_fn_false_debug.py \
        /tmp/test_check_fn_false_log_level.py \
        /tmp/check-fn-preflight.log

# Custom skills — synced to volume by entrypoint's skills_sync.py
COPY skills /opt/hermes/skills/
