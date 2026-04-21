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

# Build WASM compute module if stale
WASM_PKG="$PROJECT_ROOT/visualizer/wasm_compute/wasm_compute_bg.wasm"
WASM_SRC="$PROJECT_ROOT/wasm_compute/src/lib.rs"
if [[ ! -f "$WASM_PKG" ]] || [[ "$WASM_SRC" -nt "$WASM_PKG" ]]; then
    echo "Building WASM compute kernels (release)..."
    (cd "$PROJECT_ROOT/wasm_compute" && wasm-pack build --release --target web --out-dir "$PROJECT_ROOT/visualizer/wasm_compute" 2>&1 | tee "$BACKTESTS_DIR/wasm_build.log") || echo "wasm-pack failed -- see $BACKTESTS_DIR/wasm_build.log"
fi

# Start data server in background (stdout/stderr captured so import errors aren't silent)
echo "Starting data server on :8001..."
SERVER_LOG="$BACKTESTS_DIR/dashboard_server.log"
python -m backtester.dashboard_server "$BACKTESTS_DIR" 8001 >"$SERVER_LOG" 2>"${SERVER_LOG}.err" &
SERVER_PID=$!

# Start Vite frontend in background
echo "Starting frontend on :5555 (first run pre-bundles deps -- may take 20-30s)..."
VIZ_LOG="$BACKTESTS_DIR/vite.log"
(cd "$PROJECT_ROOT/visualizer" && npm run dev >"$VIZ_LOG" 2>"${VIZ_LOG}.err") &
VIZ_PID=$!

# Wait for Vite to actually be ready
vite_ready=0
for i in $(seq 1 60); do
    if curl -sSf --max-time 1 http://localhost:5555/ > /dev/null 2>&1; then
        vite_ready=1
        break
    fi
    [[ $i -eq 6 ]] && echo "  still waiting on Vite..."
    sleep 1
done
if [[ $vite_ready -eq 0 ]]; then
    echo "Vite did not come up within 60s. Check $VIZ_LOG / ${VIZ_LOG}.err"
fi

if command -v open &>/dev/null; then
    open "http://localhost:5555/#/mc?tab=run"
elif command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:5555/#/mc?tab=run"
fi

echo "Dashboard open at http://localhost:5555/"
echo "Server log: $SERVER_LOG   Vite log: $VIZ_LOG"
echo "Press Ctrl+C to stop."

# Wait forever until interrupted
wait
