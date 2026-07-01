#!/bin/bash
# Stop debug Edge
PROFILE="${KM_EDGE_PROFILE:-$HOME/.edge-km-debug}"
pgrep -f "user-data-dir=$PROFILE" | while read pid; do
  echo "kill $pid"
  kill "$pid" 2>/dev/null || true
done
sleep 1
echo "stopped"
