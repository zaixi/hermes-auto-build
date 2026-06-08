#!/bin/sh
set -e
VNC_PORT="${VNC_PORT:-5900}"
NOVNC_PORT="${NOVNC_PORT:-6080}"
VNC_RESOLUTION="${VNC_RESOLUTION:-1920x1080x24}"
log() { printf '[vnc-watcher] %s\n' "$*" >&2; }
CURRENT_DISPLAY=""
X11VNC_PID=""

PASSFILE=""
if [ -n "${VNC_PASSWORD:-}" ]; then
  mkdir -p /tmp/.vnc
  x11vnc -storepasswd "$VNC_PASSWORD" /tmp/.vnc/passwd >/dev/null 2>&1
  PASSFILE="/tmp/.vnc/passwd"
  log "x11vnc: password protected"
fi

NOVNC_DIR="/usr/share/novnc"
[ -d "$NOVNC_DIR" ] || { log "ERROR: $NOVNC_DIR not found"; exit 1; }
VNC_BIND="${VNC_BIND:-127.0.0.1}"
websockify --web "$NOVNC_DIR" "$VNC_BIND:$NOVNC_PORT" "127.0.0.1:$VNC_PORT" >/var/log/novnc.log 2>&1 &
log "VNC watcher started"

_find_display() {
  local d
  # Try: Xvfb :N format (traditional)
  d=$(ps -eo args= 2>/dev/null | awk -v res="$VNC_RESOLUTION" '/\/Xvfb :[0-9]+/ && index($0, res) { for(i=1;i<=NF;i++) if($i ~ /^:[0-9]+$/) { print $i; exit } }' | head -1)
  [ -n "$d" ] && { echo "$d"; return; }
  # Fallback: check /tmp/.X11-unix/ sockets
  for sock in /tmp/.X11-unix/X*; do
    [ -e "$sock" ] || continue
    d=":${sock##*/X}"
    ps -eo args= 2>/dev/null | grep -q "Xvfb" && { echo "$d"; return; }
  done
}

_start_x11vnc() {
  local disp="$1"
  X11VNC_ARGS="-display $disp -forever -shared -rfbport $VNC_PORT -noxdamage -quiet -bg -o /var/log/x11vnc.log"
  [ "${VIEW_ONLY:-0}" = "1" ] && X11VNC_ARGS="$X11VNC_ARGS -viewonly"
  [ -n "$PASSFILE" ] && X11VNC_ARGS="$X11VNC_ARGS -rfbauth $PASSFILE" || X11VNC_ARGS="$X11VNC_ARGS -nopw"
  x11vnc $X11VNC_ARGS
  sleep 1
  X11VNC_PID=$(pgrep -f "x11vnc.*-display $disp" | head -1)
  log "x11vnc running (pid=$X11VNC_PID) on DISPLAY=$disp"
  CURRENT_DISPLAY="$disp"
}

while true; do
  FOUND=$(_find_display)

  # x11vnc crash recovery
  if [ -n "$X11VNC_PID" ] && ! kill -0 "$X11VNC_PID" 2>/dev/null; then
    log "x11vnc crashed, restarting on DISPLAY=$CURRENT_DISPLAY"
    X11VNC_PID=""
    [ -n "$CURRENT_DISPLAY" ] && _start_x11vnc "$CURRENT_DISPLAY"
  fi

  # Display change detection
  if [ -n "$FOUND" ] && [ "$FOUND" != "$CURRENT_DISPLAY" ]; then
    [ -n "$X11VNC_PID" ] && kill "$X11VNC_PID" 2>/dev/null || true
    sleep 0.5
    _start_x11vnc "$FOUND"
  fi

  sleep 2
done
