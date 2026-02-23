#!/usr/bin/env bash
set -euo pipefail

TMUX_SESSION="ccbot"
TMUX_WINDOW="__main__"
TARGET="${TMUX_SESSION}:${TMUX_WINDOW}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MAX_WAIT=10  # seconds to wait for process to exit

CCBOT_DIR="${CCBOT_DIR:-$HOME/.ccbot}"
LOCK_FILE="${CCBOT_DIR}/.bot.lock"

# Check if tmux session and window exist
if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    echo "Error: tmux session '$TMUX_SESSION' does not exist"
    exit 1
fi

if ! tmux list-windows -t "$TMUX_SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$TMUX_WINDOW"; then
    echo "Error: window '$TMUX_WINDOW' not found in session '$TMUX_SESSION'"
    exit 1
fi

# Stop existing process if running (via lockfile PID)
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "Found running ccbot process (PID $PID), sending SIGTERM..."
        kill "$PID" 2>/dev/null || true

        # Wait for process to exit
        waited=0
        while kill -0 "$PID" 2>/dev/null && [ "$waited" -lt "$MAX_WAIT" ]; do
            sleep 1
            waited=$((waited + 1))
            echo "  Waiting for process to exit... (${waited}s/${MAX_WAIT}s)"
        done

        if kill -0 "$PID" 2>/dev/null; then
            echo "Process did not exit after ${MAX_WAIT}s, sending SIGKILL..."
            kill -9 "$PID" 2>/dev/null || true
            sleep 1
        fi

        echo "Process stopped."
    else
        echo "No running ccbot process (stale lockfile)"
    fi
else
    echo "No ccbot lockfile found — assuming not running"
fi

# Brief pause to let the shell settle
sleep 1

# Start ccbot
echo "Starting ccbot in $TARGET..."
tmux send-keys -t "$TARGET" "cd ${PROJECT_DIR} && uv run ccbot" Enter

# Verify startup by checking lockfile PID
sleep 3
if [ -f "$LOCK_FILE" ]; then
    NEW_PID=$(cat "$LOCK_FILE" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$NEW_PID" ] && kill -0 "$NEW_PID" 2>/dev/null; then
        echo "ccbot restarted successfully (PID $NEW_PID). Recent logs:"
        echo "----------------------------------------"
        tmux capture-pane -t "$TARGET" -p | tail -20
        echo "----------------------------------------"
    else
        echo "Warning: ccbot may not have started. Pane output:"
        echo "----------------------------------------"
        tmux capture-pane -t "$TARGET" -p | tail -30
        echo "----------------------------------------"
        exit 1
    fi
else
    echo "Warning: lockfile not found after startup. Pane output:"
    echo "----------------------------------------"
    tmux capture-pane -t "$TARGET" -p | tail -30
    echo "----------------------------------------"
    exit 1
fi
