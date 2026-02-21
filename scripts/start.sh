#!/usr/bin/env bash
# Start ccbot in the background. Kills any existing instance first.
set -euo pipefail

# Find and kill existing ccbot bot process (the Python process, not tmux)
OLD_PID=$(pgrep -f 'bin/ccbot$' || true)
if [ -n "$OLD_PID" ]; then
    echo "Killing existing ccbot (PID $OLD_PID) ..."
    kill "$OLD_PID"
    # Wait up to 5 seconds for graceful shutdown
    for i in $(seq 1 10); do
        if ! kill -0 "$OLD_PID" 2>/dev/null; then
            break
        fi
        sleep 0.5
    done
    # Force kill if still alive
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Force killing PID $OLD_PID ..."
        kill -9 "$OLD_PID"
    fi
    echo "Stopped old ccbot (PID $OLD_PID)"
else
    echo "No existing ccbot process found"
fi

# Start in background
nohup ccbot > /tmp/ccbot.log 2>&1 &
NEW_PID=$!
sleep 2

if kill -0 "$NEW_PID" 2>/dev/null; then
    echo "ccbot started (PID $NEW_PID), log: /tmp/ccbot.log"
else
    echo "ERROR: ccbot failed to start. Check /tmp/ccbot.log"
    exit 1
fi
