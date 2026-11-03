ARG BASE_TAG=latest
FROM nousresearch/hermes-agent:${BASE_TAG}

# Inherit upstream PATH and /etc/profile.d/hermes.sh; keep its launcher shim
# ahead of the baked venv. Older bases need a login-shell hook only.
RUN if [ ! -r /etc/profile.d/hermes.sh ]; then \
        mkdir -p /etc/profile.d && \
        printf '%s\n' 'export PATH="/opt/hermes/bin:/opt/hermes/.venv/bin:$PATH"' \
            > /etc/profile.d/hermes-path.sh; \
    fi

# Install additional apt packages
# file: agent 识别文件类型（whp 2026-08-21 曾因缺 file 报 command not found）
COPY scripts/image_browser.py /tmp/image_browser.py
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        jq \
        unzip \
        diffutils \
        file \
        socat \
        zip \
        shellcheck \
        fonts-wqy-zenhei && \
    browser_bin="$(python3 /tmp/image_browser.py)" && \
    if [ -z "$browser_bin" ]; then \
        apt-get install -y --no-install-recommends chromium; \
    fi && \
    python3 /tmp/image_browser.py --link /usr/local/bin/hermes-chromium && \
    rm /tmp/image_browser.py && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


# Install Feishu, Edge TTS and Silk through their upstream extras. Their exact
# versions are compatibility requirements owned by Hermes, not custom pins.
# All other custom packages are unpinned except Hindsight's plugin API bounds.
# Modern images are PM-owned/sealed: extend their declared selection and lock
# through the official build API so a later boot cannot silently drop our deps.
# pilk has no Linux wheel: the upstream image's compiler + interpreter headers
# build it here; do not assume the base interpreter remains Python 3.13.
COPY requirements-custom.txt /opt/hermes/requirements-custom.txt
COPY scripts/install_image_dependencies.py /tmp/install_image_dependencies.py
RUN if [ -x /usr/local/bin/python3 ]; then \
        build_python=/usr/local/bin/python3; \
    else build_python=python3; fi && \
    "$build_python" /tmp/install_image_dependencies.py \
        --source /opt/hermes --requirements /opt/hermes/requirements-custom.txt && \
    rm /tmp/install_image_dependencies.py

# Probe passive sealed-base diagnostics before considering a source patch. An
# upstream fix needs no rewrite; incomplete probes/unknown broken code fail closed.
COPY patches/apply_sealed_runtime_drift.py /tmp/image-regression/patches/apply_sealed_runtime_drift.py
COPY tests/test_sealed_runtime_drift.py /tmp/image-regression/tests/test_sealed_runtime_drift.py
COPY scripts/ensure_sealed_runtime_drift.py /tmp/image-regression/scripts/ensure_sealed_runtime_drift.py
RUN /opt/hermes/.venv/bin/python /tmp/image-regression/scripts/ensure_sealed_runtime_drift.py /opt/hermes && \
    rm -rf /tmp/image-regression

# A PM-managed npm may default to a versioned global prefix outside PATH.
# Keep downstream CLIs in /usr/local/bin, without modifying PM's Node store.
# Both old and new bases reuse their existing Chromium; no second download.
ENV AGENT_BROWSER_EXECUTABLE_PATH=/usr/local/bin/hermes-chromium
RUN npm install -g --prefix /usr/local --allow-scripts=@larksuite/cli,agent-browser agent-browser @larksuite/cli && \
    agent-browser --version && lark-cli --version && \
    rm -rf /tmp/* /root/.npm /root/.cache /tmp/.npm

# Fail the build before publication if imports, native Silk, XLSX or fonts fail.
COPY scripts/verify_image_dependencies.py scripts/install_image_dependencies.py /tmp/
RUN mkdir -p /tmp/image-smoke-home && chown hermes /tmp/image-smoke-home && \
    cd / && HERMES_HOME=/tmp/image-smoke-home HOME=/tmp/image-smoke-home \
        /command/s6-setuidgid hermes /opt/hermes/.venv/bin/python \
        /tmp/verify_image_dependencies.py --check-hermes && \
    rm -rf /tmp/image-smoke-home /tmp/verify_image_dependencies.py /tmp/install_image_dependencies.py

# Custom skills — synced to volume by entrypoint's skills_sync.py
COPY skills /opt/hermes/skills/
