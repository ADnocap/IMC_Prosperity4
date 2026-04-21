import sys
from pathlib import Path
from typing import Annotated, Optional

from typer import Argument, Option, Typer

from backtester.monte_carlo import default_dashboard_path, normalize_dashboard_path, run_monte_carlo_mode
from backtester.open import open_dashboard


def format_path(path: Path) -> str:
    cwd = Path.cwd()
    if path.is_relative_to(cwd):
        return str(path.relative_to(cwd))
    else:
        return str(path)


app = Typer(context_settings={"help_option_names": ["--help", "-h"]})


@app.command()
def cli(
    algorithm: Annotated[
        Path,
        Argument(
            help="Path to the Python file containing the strategy to simulate.",
            show_default=False,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    vis: Annotated[bool, Option("--vis", help="Open the Monte Carlo dashboard in the local visualizer when done.")] = False,
    out: Annotated[
        Optional[Path],
        Option(
            help="Path to dashboard JSON file (defaults to backtests/<timestamp>_monte_carlo/dashboard.json).",
            show_default=False,
            resolve_path=True,
        ),
    ] = None,
    no_out: Annotated[bool, Option("--no-out", help="Skip saving dashboard output.")] = False,
    data: Annotated[
        Optional[Path],
        Option(
            help="Path to data directory (defaults to data/prosperity4).",
            show_default=False,
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    quick: Annotated[
        bool,
        Option("--quick", help="Preset for a fast run: 100 sessions and 10 sample sessions."),
    ] = False,
    heavy: Annotated[
        bool,
        Option("--heavy", help="Preset for a full run: 1000 sessions and 100 sample sessions."),
    ] = False,
    sessions: Annotated[int, Option("--sessions", help="Number of Monte Carlo sessions to run.")] = 100,
    fv_mode: Annotated[str, Option("--fv-mode", help="Fair-value mode for the Rust simulator.")] = "simulate",
    trade_mode: Annotated[str, Option("--trade-mode", help="Trade-arrival mode for the Rust simulator.")] = "simulate",
    ipr_support: Annotated[str, Option("--ipr-support", help="Latent fair support for IPR in simulate mode.")] = "quarter",
    seed: Annotated[int, Option("--seed", help="RNG seed for the Rust simulator.")] = 20260401,
    python_bin: Annotated[
        str,
        Option("--python-bin", help="Python interpreter used for the strategy worker process."),
    ] = sys.executable,
    sample_sessions: Annotated[
        int,
        Option("--sample-sessions", help="Number of sessions to persist with full path/trace data for dashboard charts."),
    ] = 10,
    ticks_per_day: Annotated[
        int,
        Option("--ticks-per-day", help="Number of timesteps per trading day. Default 10000 matches the portal final-round eval. Use 1000 to match the portal UI backtest."),
    ] = 10000,
    quote_fraction: Annotated[
        float,
        Option("--quote-fraction", help="R2 quote overlay. <1: each level dropped with prob 1-f (e.g. 0.8 = R2 loser). >1: level volumes scaled by f (e.g. 1.25 = MAF winner uplift). Default 1.0 leaves book untouched."),
    ] = 1.0,
    maf_bid: Annotated[
        int,
        Option("--maf-bid", help="R2 Market Access Fee bid in XIRECs. Subtracted from each session's reported total PnL (bookkeeping)."),
    ] = 0,
    ipr_start_fv: Annotated[
        float,
        Option("--ipr-start-fv", help="PEPPER starting FV for the first sim day. R1 default 10000. For R2 day 1 use 13000 (portal hold-1 274082 confirmed PEPPER drift continues from R1 end)."),
    ] = 10000.0,
    replay_fv_json: Annotated[
        Optional[Path],
        Option("--replay-fv-json", help="JSON file with observed server-FV arrays for OSMIUM + PEPPER (e.g. extracted from a hold-1 portal submission). When set, overrides all FV generation so every MC session replays the exact same portal path — used for sim calibration against portal backtests."),
    ] = None,
) -> None:
    if no_out:
        print("Error: Monte Carlo mode always writes a dashboard bundle, so --no-out is not supported")
        raise SystemExit(1)
    if quick and heavy:
        print("Error: --quick and --heavy are mutually exclusive")
        raise SystemExit(1)

    if quick:
        sessions = 100
        sample_sessions = 10
    elif heavy:
        sessions = 1000
        sample_sessions = 100

    # Resolve algorithm: if not found, search newest-round first
    if not algorithm.exists():
        for subdir in ["traders/round3", "traders/round2", "traders/round1", "traders"]:
            candidate = Path(subdir) / algorithm.name
            if candidate.exists():
                algorithm = candidate.resolve()
                break
        else:
            print(f"Error: algorithm file not found: {algorithm}")
            raise SystemExit(1)

    dashboard_path = normalize_dashboard_path(out, False) or default_dashboard_path()

    dashboard = run_monte_carlo_mode(
        algorithm=algorithm,
        dashboard_path=dashboard_path,
        data_root=data,
        sessions=sessions,
        fv_mode=fv_mode,
        trade_mode=trade_mode,
        ipr_support=ipr_support,
        seed=seed,
        python_bin=python_bin,
        sample_sessions=sample_sessions,
        ticks_per_day=ticks_per_day,
        quote_fraction=quote_fraction,
        maf_bid=maf_bid,
        ipr_start_fv=ipr_start_fv,
        replay_fv_json=replay_fv_json,
    )

    total_stats = dashboard["overall"]["totalPnl"]
    print(f"Sessions: {int(total_stats['count'])}")
    print(f"Mean total PnL: {total_stats['mean']:,.2f}")
    print(f"Std total PnL: {total_stats['std']:,.2f}")
    print(f"Median total PnL: {total_stats['p50']:,.2f}")
    print(f"5%-95% range: {total_stats['p05']:,.2f} to {total_stats['p95']:,.2f}")
    print(f"Saved Monte Carlo dashboard to {format_path(dashboard_path)}")

    if vis:
        open_dashboard(dashboard_path)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
