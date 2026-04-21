from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import contextlib
import json
import threading
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.error import URLError
from urllib.request import urlopen


STATE_DIR = Path.home() / ".prosperity4mcbt"
ROOT_FILE = STATE_DIR / "dashboard_root.txt"
PID_FILE = STATE_DIR / "dashboard_server.pid"
DEFAULT_PORT = 8001
STATUS_PATH = "/__prosperity4mcbt__/status.json"
RUN_DASHBOARD_PREFIX = "/__prosperity4mcbt__/runs/"
RUNNER_PREFIX = "/__prosperity4mcbt__/runner/"

# ── Runner state (single backtest at a time) ────────────────────────
_runner_lock = threading.Lock()
_runner_state: dict | None = None
_runner_process: subprocess.Popen | None = None


def _project_root() -> Path:
    """Walk up from this file to find the repo root (contains traders/)."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "traders").is_dir():
            return p
        p = p.parent
    return Path.cwd()


def _list_traders() -> list[dict[str, object]]:
    traders_dir = _project_root() / "traders"
    if not traders_dir.is_dir():
        return []
    result = []
    # Scan round subdirectories (round1 first, then round0) and top-level
    scan_dirs = []
    for rd in sorted(traders_dir.iterdir(), reverse=True):
        if rd.is_dir() and rd.name.startswith("round"):
            scan_dirs.append(rd)
    scan_dirs.append(traders_dir)
    for d in scan_dirs:
        for f in sorted(d.glob("*.py")):
            if f.name in ("datamodel.py", "__init__.py"):
                continue
            rel = f.relative_to(_project_root())
            result.append({
                "name": f"{d.name}/{f.name}" if d != traders_dir else f.name,
                "path": str(rel).replace("\\", "/"),
                "sizeBytes": f.stat().st_size,
                "mtimeMs": int(f.stat().st_mtime_ns // 1_000_000),
            })
    return result


def _backtests_dir() -> Path:
    return _project_root() / "tmp" / "backtests"


def _run_backtest_worker(
    trader_path: Path,
    output_dir: Path,
    sessions: int,
    sample_sessions: int,
    fv_mode: str,
    trade_mode: str,
    seed: int,
    ticks_per_day: int = 10000,
) -> None:
    global _runner_state, _runner_process
    try:
        cmd = [
            sys.executable, "-m", "backtester.cli_mc",
            str(trader_path),
            "--sessions", str(sessions),
            "--sample-sessions", str(sample_sessions),
            "--fv-mode", fv_mode,
            "--trade-mode", trade_mode,
            "--seed", str(seed),
            "--out", str(output_dir / "dashboard.json"),
            "--ticks-per-day", str(ticks_per_day),
        ]
        env = {**os.environ, "PATH": os.environ.get("PATH", "") + os.pathsep + str(Path.home() / ".cargo" / "bin")}
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(_project_root()),
            env=env,
        )
        with _runner_lock:
            _runner_process = process
            if _runner_state is not None:
                _runner_state["pid"] = process.pid

        stdout, stderr = process.communicate()

        with _runner_lock:
            _runner_process = None
            if _runner_state is None:
                return
            if process.returncode == 0:
                ROOT_FILE.write_text(str(output_dir.resolve()))
                _runner_state["status"] = "complete"
                _runner_state["endTime"] = time.time()
                _runner_state["dashboardUrl"] = f"{RUN_DASHBOARD_PREFIX}{output_dir.name}/dashboard.json"
                _runner_state["stdout"] = stdout.decode("utf-8", errors="replace")[-2000:]
            else:
                _runner_state["status"] = "failed"
                _runner_state["endTime"] = time.time()
                _runner_state["error"] = stderr.decode("utf-8", errors="replace")[-2000:]
    except Exception as exc:
        with _runner_lock:
            _runner_process = None
            if _runner_state is not None:
                _runner_state["status"] = "failed"
                _runner_state["endTime"] = time.time()
                _runner_state["error"] = str(exc)


def _list_runs(current_root: Path) -> tuple[list[dict[str, object]], str | None]:
    current_root = current_root.resolve()
    candidates: list[Path] = []

    # Search siblings of current_root (original behavior for when root is a run dir)
    runs_parent = current_root.parent
    if runs_parent.exists():
        for child in runs_parent.iterdir():
            if child.is_dir() and (child / "dashboard.json").exists():
                candidates.append(child.resolve())

    # Also search children of current_root (for when root is the backtests/ dir)
    if current_root.exists():
        for child in current_root.iterdir():
            if child.is_dir() and (child / "dashboard.json").exists() and child.resolve() not in candidates:
                candidates.append(child.resolve())

    if (current_root / "dashboard.json").exists() and current_root.resolve() not in candidates:
        candidates.append(current_root.resolve())

    candidates.sort(
        key=lambda path: (path / "dashboard.json").stat().st_mtime_ns if (path / "dashboard.json").exists() else 0,
        reverse=True,
    )

    runs: list[dict[str, object]] = []
    for run_dir in candidates:
        dashboard_path = run_dir / "dashboard.json"
        stat = dashboard_path.stat()
        runs.append(
            {
                "id": run_dir.name,
                "label": run_dir.name,
                "mtimeMs": int(stat.st_mtime_ns // 1_000_000),
                "dashboardUrl": f"{RUN_DASHBOARD_PREFIX}{run_dir.name}/dashboard.json",
            }
        )

    current_run_id = current_root.name if (current_root / "dashboard.json").exists() else (runs[0]["id"] if runs else None)
    return runs, current_run_id


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        """Resolve file paths: try the server root first, then the latest run directory."""
        result = super().translate_path(path)
        if not os.path.exists(result):
            # File not found in root — try serving from the latest run subdirectory
            root = Path(getattr(self, "directory", ".")).resolve()
            _, current_run_id = _list_runs(root)
            if current_run_id:
                alt = root / current_run_id / path.lstrip("/")
                if alt.exists():
                    return str(alt)
        return result

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == STATUS_PATH:
            self._serve_status()
            return
        if path.startswith(RUN_DASHBOARD_PREFIX):
            self._serve_run_dashboard(path)
            return
        if path.startswith(RUNNER_PREFIX):
            self._handle_runner_get(path)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith(RUNNER_PREFIX):
            self._handle_runner_post(path)
            return
        self.send_error(404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    # ── Status / runs ───────────────────────────────────────────────

    def _serve_status(self) -> None:
        root = Path(getattr(self, "directory", ".")).resolve()
        runs, current_run_id = _list_runs(root)

        # Find the best dashboard: root/dashboard.json, or the latest run's dashboard
        dashboard_path = root / "dashboard.json"
        if not dashboard_path.exists() and current_run_id:
            candidate = root / current_run_id / "dashboard.json"
            if candidate.exists():
                dashboard_path = candidate

        dashboard_exists = dashboard_path.exists()
        payload = {
            "root": str(root),
            "dashboardExists": dashboard_exists,
            "dashboardMtimeMs": int(dashboard_path.stat().st_mtime_ns // 1_000_000) if dashboard_exists else None,
            "dashboardSizeBytes": int(dashboard_path.stat().st_size) if dashboard_exists else None,
            "currentRunId": current_run_id,
            "runs": runs,
        }
        self._send_json(payload)

    def _serve_run_dashboard(self, path: str) -> None:
        root = Path(getattr(self, "directory", ".")).resolve()
        runs, _ = _list_runs(root)
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) != 4 or parts[:2] != ["__prosperity4mcbt__", "runs"] or parts[3] != "dashboard.json":
            self.send_error(404)
            return

        run_id = parts[2]
        matching = next((run for run in runs if run["id"] == run_id), None)
        if matching is None:
            self.send_error(404)
            return

        # Check both as child of root (root=backtests/) and as sibling (root=a run dir)
        dashboard_path = root / run_id / "dashboard.json"
        if not dashboard_path.exists():
            dashboard_path = root.parent / run_id / "dashboard.json"
        if not dashboard_path.exists():
            self.send_error(404)
            return

        body = dashboard_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── Runner endpoints ────────────────────────────────────────────

    def _handle_runner_get(self, path: str) -> None:
        route = path[len(RUNNER_PREFIX):]
        if route == "traders":
            self._send_json(_list_traders())
        elif route == "status":
            self._serve_runner_status()
        else:
            self.send_error(404)

    def _handle_runner_post(self, path: str) -> None:
        route = path[len(RUNNER_PREFIX):]
        if route == "start":
            self._start_backtest()
        elif route == "cancel":
            self._cancel_backtest()
        elif route == "clear":
            self._clear_runner()
        else:
            self.send_error(404)

    def _serve_runner_status(self) -> None:
        with _runner_lock:
            state = dict(_runner_state) if _runner_state else None
        self._send_json({"run": state})

    def _start_backtest(self) -> None:
        global _runner_state
        body = json.loads(self._read_body())
        trader_name = body.get("trader", "")
        sessions = body.get("sessions", 100)
        sample_sessions = body.get("sampleSessions", 10)
        fv_mode = body.get("fvMode", "simulate")
        trade_mode = body.get("tradeMode", "simulate")
        seed = body.get("seed", 20260401)
        ticks_per_day = body.get("ticksPerDay", 10000)

        trader_path = _project_root() / "traders" / trader_name
        if not trader_path.exists():
            self._send_json({"error": f"Trader not found: {trader_name}"}, 404)
            return

        with _runner_lock:
            if _runner_state is not None and _runner_state.get("status") == "running":
                self._send_json({"error": "A backtest is already running"}, 409)
                return

            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            safe_trader = trader_name.replace(".py", "").replace("/", "_").replace("\\", "_")
            run_id = f"{safe_trader}_{ts}"
            output_dir = _backtests_dir() / run_id
            output_dir.mkdir(parents=True, exist_ok=True)

            _runner_state = {
                "id": run_id,
                "trader": trader_name,
                "sessions": sessions,
                "sampleSessions": sample_sessions,
                "fvMode": fv_mode,
                "tradeMode": trade_mode,
                "seed": seed,
                "ticksPerDay": ticks_per_day,
                "status": "running",
                "startTime": time.time(),
                "endTime": None,
                "error": None,
                "pid": None,
                "outputDir": str(output_dir),
                "dashboardUrl": None,
                "stdout": None,
            }

        thread = threading.Thread(
            target=_run_backtest_worker,
            args=(trader_path, output_dir, sessions, sample_sessions, fv_mode, trade_mode, seed, ticks_per_day),
            daemon=True,
        )
        thread.start()

        with _runner_lock:
            self._send_json({"run": dict(_runner_state)})

    def _cancel_backtest(self) -> None:
        global _runner_state, _runner_process
        with _runner_lock:
            if _runner_state is None or _runner_state.get("status") != "running":
                self._send_json({"error": "No running backtest to cancel"}, 404)
                return
            if _runner_process is not None:
                _runner_process.terminate()
            _runner_state["status"] = "failed"
            _runner_state["endTime"] = time.time()
            _runner_state["error"] = "Cancelled by user"
            self._send_json({"run": dict(_runner_state)})

    def _clear_runner(self) -> None:
        global _runner_state
        with _runner_lock:
            if _runner_state is not None and _runner_state.get("status") == "running":
                self._send_json({"error": "Cannot clear while running"}, 409)
                return
            _runner_state = None
        self._send_json({"ok": True})


def serve_dashboard(root: Path, port: int = 8001) -> None:
    root = root.resolve()
    handler = partial(DashboardRequestHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, SystemError):
        return False


def read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def read_root() -> Path | None:
    try:
        return Path(ROOT_FILE.read_text().strip()).resolve()
    except Exception:
        return None


def terminate_existing_server() -> None:
    pid = read_pid()
    if pid is None:
        return
    if not is_alive(pid):
        with contextlib.suppress(Exception):
            PID_FILE.unlink()
        with contextlib.suppress(Exception):
            ROOT_FILE.unlink()
        return

    with contextlib.suppress(Exception):
        os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 2.0
    while time.time() < deadline and is_alive(pid):
        time.sleep(0.05)
    if is_alive(pid):
        with contextlib.suppress(Exception):
            os.kill(pid, signal.SIGKILL)

    with contextlib.suppress(Exception):
        PID_FILE.unlink()
    with contextlib.suppress(Exception):
        ROOT_FILE.unlink()


def wait_for_server(port: int, timeout_seconds: float = 5.0) -> None:
    deadline = time.time() + timeout_seconds
    url = f"http://127.0.0.1:{port}{STATUS_PATH}"
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except URLError:
            time.sleep(0.05)
        except Exception:
            time.sleep(0.05)
    raise RuntimeError(f"dashboard server did not become ready on port {port}")


def ensure_dashboard_server(root: Path, port: int = DEFAULT_PORT) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    previous_root = read_root()
    ROOT_FILE.write_text(str(root))

    current_pid = read_pid()
    if current_pid is not None and is_alive(current_pid):
        if previous_root == root:
            return
        terminate_existing_server()

    process = subprocess.Popen(
        [sys.executable, "-m", "backtester.dashboard_server", str(root), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    PID_FILE.write_text(str(process.pid))
    wait_for_server(port)


def main() -> None:
    if len(sys.argv) not in (2, 3):
        raise SystemExit("usage: python -m backtester.dashboard_server <root> [port]")

    root = Path(sys.argv[1]).resolve()
    port = int(sys.argv[2]) if len(sys.argv) == 3 else 8001
    serve_dashboard(root, port)


if __name__ == "__main__":
    main()
