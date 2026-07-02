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

EDGE_BIN="/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"

# Window anchored inside the built-in (main) display's visible area (only used
# in headed mode). macOS clamps extreme negative coords onto the nearest
# monitor, which on a multi-display setup pushed the window onto the external
# screen — so we use a small positive origin instead of the old -32000 trick.
WINPOS="${KM_EDGE_WINPOS:-40,40}"
WINSIZE="${KM_EDGE_WINSIZE:-1400,1000}"

# Launch mode:
#   Default = HEADLESS. A headless browser has no window at all, so it can
#   never steal focus, switch Spaces, or pop out of a fullscreen app — the only
#   way to be truly non-disruptive under Stage Manager / fullscreen. Headless
#   backup was verified to fetch body text, PNG images and draw.io SVGs fine.
#   The one tradeoff is the UA carries a "HeadlessChrome" token (a theoretical
#   anti-scraping signal), so set KM_EDGE_HEADED=1 to fall back to the windowed
#   background launch when you need to watch/debug the browser.
if [ "${KM_EDGE_HEADED:-0}" = "1" ]; then
  echo "launching debug Edge (HEADED, background) on port=$PORT"
  open -g -n -a "Microsoft Edge" --args \
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
    about:blank > /tmp/edge_km_debug.log 2>&1
else
  echo "launching debug Edge (HEADLESS, no window) on port=$PORT"
  "$EDGE_BIN" \
    --headless=new \
    --remote-debugging-port="$PORT" \
    --user-data-dir="$PROFILE" \
    --no-first-run \
    --no-default-browser-check \
    --disable-sync \
    --disable-features=DialMediaRouteProvider,EdgeSync \
    about:blank > /tmp/edge_km_debug.log 2>&1 &
fi
sleep 3

# Verify
if curl -sSf "http://127.0.0.1:$PORT/json/version" > /dev/null; then
  echo "CDP ready on 127.0.0.1:$PORT"
else
  echo "CDP not responding"
  exit 1
fi

# Edge account sync re-opens the user's work tabs on launch regardless of
# --disable-sync, and it does so ASYNCHRONOUSLY — tabs keep trickling back for
# several seconds. A one-shot cleanup misses the late arrivals, so we sweep
# repeatedly over a short window and keep a single blank sandbox tab.
/usr/bin/python3 - "$PORT" <<'PYEOF'
import json, sys, time, urllib.request
port = sys.argv[1]

def list_pages():
    try:
        tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5))
    except Exception:
        return None
    return [t for t in tabs if t.get('type') == 'page']

def close(tid):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{tid}", timeout=5)
        return True
    except Exception:
        return False

total_closed = 0
# Sweep for ~10s: sync usually finishes restoring within a few seconds.
for _ in range(10):
    pages = list_pages()
    if pages is None:
        break
    for t in pages:
        if not t.get('url','').startswith('about:blank'):
            if close(t['id']):
                total_closed += 1
    time.sleep(1)

# Ensure at least one blank sandbox tab remains.
pages = list_pages() or []
if not any(p.get('url','').startswith('about:blank') for p in pages):
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/json/new?about:blank", method='PUT'), timeout=5)
    except Exception:
        pass
print(f"tab cleanup: closed {total_closed} synced tab(s) over 10s, kept blank sandbox")
PYEOF
