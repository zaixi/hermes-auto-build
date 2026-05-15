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

# Fix TUI stale-check: _tui_build_needed runs _hermes_ink_bundle_stale which
# looks for "ink-bundle.js" (doesn't exist), triggering a spurious rebuild.
# Short-circuit when dist/entry.js already exists (prebuilt bundle).
# Upstream fix: remove _tui_build_needed entirely, use prebuilt detection in
# _tui_need_npm_install. Until this reaches :latest, patch here.
RUN sed -i '/^def _tui_build_needed/,/^def /{
    /^def _tui_build_needed/a\
    entry = tui_dir \/ "dist" \/ "entry.js"\
    if entry.is_file():\
        return False
}' /opt/hermes/hermes_cli/main.py
