ARG BASE_TAG=latest
FROM nousresearch/hermes-agent:${BASE_TAG}

# Supported PM-era bases own PATH and /etc/profile.d/hermes.sh. Keep their
# launcher shim ahead of the baked venv; runtime smoke verifies both shell modes.

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
COPY tests/test_pm_tool_staging_live.py /tmp/
# stage_tools locks both stores. Keep the image store root-owned; prepare only
# node as root in a separate seed, then hand that disposable store to hermes.
#
# XDG contract: the base ships ENV XDG_RUNTIME_DIR=/tmp/hermes-runtime and
# stage2 only adopts a directory owned by root or the remapped hermes UID. A
# build-UID-owned tree therefore survives into production, where PUID 1000
# cannot open agent-browser's socket dir. Pin the expected base value (a base
# that moves it must fail this build, never be silently deleted as root),
# keep both smokes on a private XDG dir, then leave an empty root-owned seed.
RUN cd /opt/hermes && \
    runtime_dir=/tmp/hermes-runtime && \
    test "${XDG_RUNTIME_DIR:-}" = "$runtime_dir" || \
        { echo "base moved XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-unset}; update the pin in this Dockerfile" >&2; exit 1; } && \
    /opt/hermes/pm-runtime/bin/python -c \
        "from pathlib import Path; from pm import stage_tools; from pm.store import current_target; stage_tools(['node'], source_store=Path('/opt/hermes/tools'), out=Path('/tmp/image-tool-seed'), target=current_target())" && \
    chown -R hermes /tmp/image-tool-seed && \
    mkdir -p /tmp/image-smoke-home/runtime && \
    chown -R hermes /tmp/image-smoke-home && \
    export XDG_RUNTIME_DIR=/tmp/image-smoke-home/runtime && \
    cd / && HERMES_HOME=/tmp/image-smoke-home HOME=/tmp/image-smoke-home \
        /command/s6-setuidgid hermes /opt/hermes/.venv/bin/python \
        /tmp/verify_image_dependencies.py --check-hermes && \
    HERMES_TOOL_SOURCE=/opt/hermes \
        HERMES_TOOL_PM_PYTHON=/opt/hermes/pm-runtime/bin/python \
        HERMES_TOOL_SEED_STORE=/tmp/image-tool-seed \
        HERMES_IMAGE_ADAPTER=/tmp/install_image_dependencies.py \
        /command/s6-setuidgid hermes /opt/hermes/.venv/bin/python \
        /tmp/test_pm_tool_staging_live.py && \
    rm -rf /tmp/image-smoke-home /tmp/image-tool-seed /tmp/verify_image_dependencies.py \
        /tmp/install_image_dependencies.py /tmp/test_pm_tool_staging_live.py && \
    test ! -L "$runtime_dir" && rm -rf "$runtime_dir" && \
    install -d -o root -g root -m 0700 "$runtime_dir" && \
    test -z "$(ls -A "$runtime_dir")" && \
    test "$(stat -c '%u:%g %a' "$runtime_dir")" = "0:0 700"
