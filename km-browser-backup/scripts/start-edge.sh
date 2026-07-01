#!/bin/bash
# Start offscreen Edge with debug port for KM backup
set -e

PORT="${KM_EDGE_PORT:-9333}"
PROFILE="${KM_EDGE_PROFILE:-$HOME/.edge-km-debug}"

# Kill existing debug edge (match the exact user-data-dir; pgrep -f alone was
# unreliable and left stale processes holding the port).
for pid in $(pgrep -f "user-data-dir=$PROFILE" 2>/dev/null); do
  kill -9 "$pid" 2>/dev/null || true
done
# Also reap anything still holding the debug port.
for pid in $(lsof -ti ":$PORT" 2>/dev/null); do
  kill -9 "$pid" 2>/dev/null || true
done
sleep 2

# Check port free
if lsof -i ":$PORT" >/dev/null 2>&1; then
  echo "port $PORT still busy, aborting"
  exit 1
fi

# Window anchored inside the built-in (main) display's visible area.
# macOS clamps extreme negative coords onto the nearest monitor, which on a
# multi-display setup (external monitor at negative origin) pushed the window
# onto the external screen. Keep it at a small positive origin so it always
# lands on the built-in display. Override with KM_EDGE_WINDOW if needed.
WINPOS="${KM_EDGE_WINPOS:-40,40}"
WINSIZE="${KM_EDGE_WINSIZE:-1400,1000}"

"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE" \
  --window-position="$WINPOS" \
  --window-size="$WINSIZE" \
  --no-first-run \
  --no-default-browser-check \
  --no-restore-session-state \
  --hide-crash-restore-bubble \
  --disable-sync \
  --disable-features=DialMediaRouteProvider,EdgeSync \
  about:blank > /tmp/edge_km_debug.log 2>&1 &

PID=$!
echo "started PID=$PID port=$PORT"
sleep 3

# Verify
if curl -sSf "http://127.0.0.1:$PORT/json/version" > /dev/null; then
  echo "CDP ready on 127.0.0.1:$PORT"
else
  echo "CDP not responding"
  exit 1
fi

# Edge account sync re-opens the user's work tabs on launch regardless of
# --disable-sync. Close every tab that isn't about:blank so the debug browser
# is a clean sandbox and never mirrors the user's working Edge.
/usr/bin/python3 - "$PORT" <<'PYEOF'
import json, sys, urllib.request
port = sys.argv[1]
try:
    tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5))
except Exception as e:
    print(f"tab cleanup skipped: {e}"); sys.exit(0)
pages = [t for t in tabs if t.get('type') == 'page']
blanks = [t for t in pages if t.get('url','').startswith('about:blank')]
closed = 0
for t in pages:
    if t.get('url','').startswith('about:blank'):
        continue
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{t['id']}", timeout=5)
        closed += 1
    except Exception:
        pass
# Ensure at least one blank tab remains.
if not blanks:
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/json/new?about:blank", method='PUT'), timeout=5)
    except Exception:
        pass
print(f"tab cleanup: closed {closed} synced tab(s), kept blank sandbox")
PYEOF
