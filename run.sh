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

# Kill any leftover data server from a previous run
PID_FILE="$HOME/.prosperity4mcbt/dashboard_server.pid"
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$OLD_PID" ]]; then
        kill "$OLD_PID" 2>/dev/null || true
    fi
fi

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
echo "Starting frontend on :5555..."
(cd "$PROJECT_ROOT/visualizer" && npm run dev) &
VIZ_PID=$!

# Wait for frontend to be ready, then open browser on Run tab
sleep 3
if command -v open &>/dev/null; then
    open "http://localhost:5555/#/mc?tab=run"
elif command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:5555/#/mc?tab=run"
fi

echo "Dashboard open at http://localhost:5555/"
echo "Press Ctrl+C to stop."

# Wait forever until interrupted
wait
