#!/usr/bin/env bash
# Launch the backtest dashboard (frontend + data server).
# Run backtests from the browser's Run tab.
#
# Usage:  ./run.sh

set -euo pipefail

export PYTHONIOENCODING=utf-8
export PYTHONDONTWRITEBYTECODE=1

# Add cargo to PATH
if [[ ":$PATH:" != *":$HOME/.cargo/bin:"* ]]; then
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# Use absolute paths
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKTESTS_DIR="$PROJECT_ROOT/tmp/backtests"
mkdir -p "$BACKTESTS_DIR"

# Kill any leftover data server from a previous run (both PID file and port holders)
PID_FILE="$HOME/.prosperity4mcbt/dashboard_server.pid"
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$OLD_PID" ]]; then
        kill "$OLD_PID" 2>/dev/null || true
    fi
fi

# Kill whatever is listening on :8001 / :5555 -- prior runs don't always clean up.
for port in 8001 5555; do
    if command -v lsof &>/dev/null; then
        holders=$(lsof -tiTCP:$port -sTCP:LISTEN 2>/dev/null || true)
        for pid in $holders; do
            echo "  killing stale process $pid on :$port"
            kill -9 "$pid" 2>/dev/null || true
        done
    fi
done
sleep 0.3

cleanup() {
    echo -e "\nShutting down..."
    [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true
    [[ -n "${VIZ_PID:-}" ]]    && kill "$VIZ_PID" 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

# Start data server in background
echo "Starting data server on :8001..."
python -m backtester.dashboard_server "$BACKTESTS_DIR" 8001 &
SERVER_PID=$!

# Start Vite frontend in background
echo "Starting frontend on :5555 (first run pre-bundles deps -- may take 20-30s)..."
(cd "$PROJECT_ROOT/visualizer" && npm run dev) &
VIZ_PID=$!

# Wait for Vite to actually be ready
for i in $(seq 1 60); do
    if curl -sSf --max-time 1 http://localhost:5555/ > /dev/null 2>&1; then
        break
    fi
    [[ $i -eq 6 ]] && echo "  still waiting on Vite..."
    sleep 1
done

if command -v open &>/dev/null; then
    open "http://localhost:5555/#/mc?tab=run"
elif command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:5555/#/mc?tab=run"
fi

echo "Dashboard open at http://localhost:5555/"
echo "Press Ctrl+C to stop."

# Wait forever until interrupted
wait
