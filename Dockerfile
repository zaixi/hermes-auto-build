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
        shellcheck \
        fonts-wqy-zenhei && \
    if [ ! -s /etc/hermes/agent-browser-executable-path ]; then \
        apt-get install -y --no-install-recommends chromium; \
    fi && \
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

# Separate passive sealed-base diagnostics from runtime plugin selections. Apply
# only during image construction; unknown upstream implementations fail closed.
COPY patches/apply_sealed_runtime_drift.py /tmp/image-regression/patches/apply_sealed_runtime_drift.py
COPY tests/test_sealed_runtime_drift.py /tmp/image-regression/tests/test_sealed_runtime_drift.py
RUN /opt/hermes/.venv/bin/python /tmp/image-regression/patches/apply_sealed_runtime_drift.py /opt/hermes && \
    if [ -f /opt/hermes/pm/build_env.py ]; then \
        HERMES_SOURCE_ROOT=/opt/hermes HERMES_TEST_USE_SOURCE_AS_IS=1 PYTHONDONTWRITEBYTECODE=1 \
            /opt/hermes/.venv/bin/python /tmp/image-regression/tests/test_sealed_runtime_drift.py; \
    fi && \
    rm -rf /tmp/image-regression

# npm tools intentionally follow compatible available releases, without custom
# pins. Reuse the official image's managed Chromium instead of downloading a
# second browser; legacy base images retain their existing installation path.
RUN npm install -g --allow-scripts=@larksuite/cli,agent-browser agent-browser @larksuite/cli && \
    if [ ! -s /etc/hermes/agent-browser-executable-path ]; then agent-browser install; fi && \
    rm -rf /tmp/* /root/.npm /root/.cache /tmp/.npm

# Fail the build before publication if imports, native Silk, XLSX or fonts fail.
COPY scripts/verify_image_dependencies.py scripts/install_image_dependencies.py /tmp/
RUN mkdir -p /tmp/image-smoke-home && chown hermes /tmp/image-smoke-home && \
    cd / && HERMES_HOME=/tmp/image-smoke-home HOME=/tmp/image-smoke-home \
        /command/s6-setuidgid hermes /opt/hermes/.venv/bin/python \
        /tmp/verify_image_dependencies.py --check-hermes && \
    rm -rf /tmp/image-smoke-home /tmp/verify_image_dependencies.py /tmp/install_image_dependencies.py

# Backport upstream #62930 / #86417: a normal availability gate returning
# False means an optional capability is off, not that its probe crashed.
# Keep exceptions and recent-success flakes at WARNING; steady-state False
# verdicts may be DEBUG (our backport) or INFO (upstream v2026.9.21+) so they
# do not flood Docker warning logs.
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
