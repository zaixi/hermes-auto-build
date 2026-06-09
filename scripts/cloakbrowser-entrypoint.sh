#!/bin/bash
set -e

# Clean up stale Xvfb locks from previous container instances
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Start Xvfb virtual display
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
sleep 1

# Create VNC password file
mkdir -p /tmp/.vnc 2>/dev/null
VNC_PASS="${VNC_PASSWORD:-hermes}"
x11vnc -storepasswd "$VNC_PASS" /tmp/.vnc/passwd >/dev/null 2>&1

# Start x11vnc
VNC_PORT="${VNC_PORT:-5900}"
x11vnc -display :99 -forever -shared -rfbport "$VNC_PORT" \
  -noxdamage -quiet -bg -rfbauth /tmp/.vnc/passwd -o /var/log/x11vnc.log 2>/dev/null

# Start noVNC (websockify)
NOVNC_PORT="${NOVNC_PORT:-8080}"
websockify --web /usr/share/novnc "$NOVNC_PORT" 127.0.0.1:"$VNC_PORT" >/var/log/novnc.log 2>&1 &

# Determine persistent data directory
DATA_DIR="${CLOAKSERVE_DATA_DIR:-/root/.cloakbrowser/data}"
mkdir -p "$DATA_DIR"
PROFILE_DIR="$DATA_DIR/__default__"

# Clean up stale Chrome locks from previous runs
rm -f "$PROFILE_DIR"/Singleton* "$PROFILE_DIR"/Lock 2>/dev/null

# Start Chrome directly with CDP (bound to 127.0.0.1 only — nginx proxy handles external)
CHROME_BIN="/root/.cloakbrowser/chromium-146.0.7680.177.5/chrome"
export DISPLAY=:99

"$CHROME_BIN" \
  --no-sandbox \
  --no-first-run \
  --no-default-browser-check \
  --disable-dev-shm-usage \
  --disable-extensions \
  --disable-popup-blocking \
  --disable-background-networking \
  --metrics-recording-only \
  --ignore-gpu-blocklist \
  --remote-debugging-port=5100 \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="$PROFILE_DIR" \
  > /dev/null 2>&1 &

CHROME_PID=$!
echo "Chrome started (PID=$CHROME_PID)"

# Wait for Chrome CDP to be ready
for i in $(seq 1 30); do
  if curl -s http://127.0.0.1:5100/json/version >/dev/null 2>&1; then
    echo "Chrome CDP ready on port 5100"
    break
  fi
  sleep 1
done

# Start nginx CDP proxy (port 5101 → Chrome port 5100 with Host header rewrite)
# This replaces socat — nginx handles Host header + WebSocket URL rewriting
CDP_PORT="${CDP_PORT:-5101}"
echo "Starting nginx CDP proxy on port $CDP_PORT..."
nginx -c /etc/nginx/nginx.conf 2>/dev/null
# Verify nginx is listening
for i in $(seq 1 5); do
  if curl -s http://127.0.0.1:"$CDP_PORT"/json/version >/dev/null 2>&1; then
    echo "nginx CDP proxy ready on port $CDP_PORT"
    break
  fi
  sleep 1
done

# Auto-resize Chrome window
(
  for i in $(seq 1 20); do
    sleep 2
    WID=$(xdotool search --name "Chrom\|New Tab\|what" 2>/dev/null | head -1)
    if [ -n "$WID" ]; then
      xdotool windowmove "$WID" 0 0 2>/dev/null
      xdotool windowsize "$WID" 1920 1080 2>/dev/null
      break
    fi
  done
) &

# Keep container running (wait for Chrome to exit)
wait $CHROME_PID
