import webbrowser
from pathlib import Path

from backtester.dashboard_server import ensure_dashboard_server


def open_dashboard(output_file: Path) -> None:
    ensure_dashboard_server(output_file.parent)
    if output_file.name == "dashboard.json":
        webbrowser.open("http://localhost:5555/")
    else:
        webbrowser.open(f"http://localhost:5555/?open=http://localhost:8001/{output_file.name}")
