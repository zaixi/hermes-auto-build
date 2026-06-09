#!/bin/bash
set -e

# Clean up stale Xvfb locks from previous container instances
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Start Xvfb virtual display
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
sleep 1

# Create VNC password file
mkdir -p /tmp/.vnc
VNC_PASS="${VNC_PASSWORD:-hermes}"
x11vnc -storepasswd "$VNC_PASS" /tmp/.vnc/passwd >/dev/null 2>&1

# Start x11vnc
VNC_PORT="${VNC_PORT:-5900}"
x11vnc -display :99 -forever -shared -rfbport "$VNC_PORT" \
  -noxdamage -quiet -bg -rfbauth /tmp/.vnc/passwd -o /var/log/x11vnc.log 2>/dev/null

# Start noVNC (websockify)
NOVNC_PORT="${NOVNC_PORT:-8080}"
websockify --web /usr/share/novnc "$NOVNC_PORT" 127.0.0.1:"$VNC_PORT" >/var/log/novnc.log 2>&1 &

# Extra: resize Chromium window after it starts (use xdotool polling)
(
  for i in $(seq 1 20); do
    sleep 2
    WID=$(xdotool search --name "Chrom\|cloak\|Navigator" 2>/dev/null | head -1)
    if [ -n "$WID" ]; then
      xdotool windowmove "$WID" 0 0 2>/dev/null
      xdotool windowsize "$WID" 1920 1080 2>/dev/null
      break
    fi
  done
) &

# Run user command (typically cloakserve)
exec "$@"
