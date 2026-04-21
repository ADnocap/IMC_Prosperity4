# Data Analysis Workshop

The **Workshop** tab in the local dashboard is a browser-based market-microstructure lab for every historical round of IMC Prosperity we have data for (both Prosperity 3 and Prosperity 4). It ingests the raw per-tick order-book snapshots and the trade tape, lets you slice by round / day / product, and renders the panels professional quant researchers reach for first on orderbook data: microprice, spread, depth heatmap, queue-imbalance signal, order-flow-imbalance, mark-out by counterparty, effective-vs-realized spread, return correlation matrix, lead-lag CCF, pair spread with OU half-life, observation-driven β table, and intraday seasonality.

All compute runs in **Rust compiled to WebAssembly**, dispatched to a Web Worker so the UI stays responsive even on the biggest rounds (P3 R7 has 580 k rows across 15 products).

**TL;DR — for the full tour, load `prosperity3 → round5`**. It's the only round that fires every tab (named bot counterparties + observations + 16 products with baskets and components).

---

## First-time setup

The Workshop ships with the rest of the dashboard; there's no separate install, but you do need one tool the other parts of the repo don't use.

### Prerequisites

| Tool           | Used for                                      | Install                   |
| -------------- | --------------------------------------------- | ------------------------- |
| Python 3.13    | Data server (`backtester.dashboard_server`)   | https://python.org        |
| Node 18+ / npm | Vite frontend                                 | https://nodejs.org        |
| Rust (stable)  | Already required for `rust_simulator`         | https://rustup.rs         |
| `wasm-pack`    | Compiles the workshop compute kernels to WASM | `cargo install wasm-pack` |

One-time from the repo root:

```bash
# Python side (installs prosperity3bt + prosperity4mcbt CLIs too)
pip install -e .

# Frontend deps
cd visualizer && npm install && cd ..

# WASM compute (one-shot -- `./run.ps1` / `./run.sh` rebuild automatically when src changes)
cd wasm_compute && wasm-pack build --release --target web --out-dir ../visualizer/wasm_compute && cd ..
```

### Launch

**Windows:**

```powershell
.\run.ps1
```

**macOS / Linux:**

```bash
./run.sh
```

Both scripts:

1. Kill any leftover dashboard server on :8001 and Vite on :5555 from a prior run.
2. Rebuild the WASM compute kernel if `wasm_compute/src/lib.rs` is newer than the built artefact.
3. Start the Python data server (stdout/stderr captured to `tmp/backtests/dashboard_server.log`).
4. Start the Vite dev server (`tmp/backtests/vite.log`).
5. Poll `http://localhost:5555/` until Vite is ready (up to 60s on a cold start -- first run pre-bundles deps).
6. Open the dashboard in your browser.

**First run** will take **20–30 seconds** for Vite to pre-bundle deps (papaparse, arquero, mantine-react-table, etc.). Subsequent runs are near-instant. If the browser opens before Vite is ready, the script will print `still waiting on Vite...` and wait.

Data lives under `data/prosperity{3,4}/round<N>/`. The Workshop's data server walks this directory on start-up.

---

## The tour

Click **Workshop** in the top nav. The page has a left rail for data selection and a main area with seven tabs. Tabs are **schema-gated** — they auto-disable when the loaded files don't contain what they need.

### Data source (left rail)

| Control      | What it does                                                                                                                                                                   |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Version**  | `prosperity3` / `prosperity4`. Populated from the `data/` directory.                                                                                                           |
| **Round**    | Populated from the selected version.                                                                                                                                           |
| **Day**      | One specific day **or "All days"** — concat mode stitches days together with a synthetic cumulative tick counter. Day boundaries get a dashed line on every time-series panel. |
| **Products** | Multi-select. Empty = all products. Populated from the data actually in the selected files.                                                                                    |

The small badges below the selectors show how many price / trade / observation rows are loaded.

### Tab: Overview

Always available when a prices file loads.

- **Mid / Microprice** — per-product mid-price time series. Toggle shows the **Stoikov microprice** (`(bid·askVol + ask·bidVol) / (bidVol+askVol)`) dashed on top of the mid. Microprice is a better fair-value anchor than mid whenever book volumes are asymmetric.
- **Bid-ask spread** — per-product `ask1 − bid1` plotted over time + histogram. Header strip reports μ, σ, and P05/50/95 per product.

### Tab: LOB (enables with a bid/ask ladder in the prices file)

The order-book edge-hunting panels.

- **Book depth (stacked)** — signed volume: bid levels (blue shades) stacked below zero, ask levels (red shades) above. L1 dark on top, L3 light at the bottom. Per-product picker. Ladder depth detected automatically — works for 3 levels today, more in future rounds.
- **Queue imbalance → next-k-tick return** — the single highest-signal LOB panel. Scatter of `I = (bidVol − askVol)/(bidVol + askVol)` at top-of-book against the next-k-tick mid change, with a red **binned conditional-mean curve** overlaid. The curve's shape **is** the tradable signal — if it's monotone and positive-slope, the imbalance predicts direction. Horizon toggle: 1, 5, 10, 50 ticks.
- **OFI → next-tick return** — Cont-Kukanov Order Flow Imbalance: signed size changes at top of book (bid events positive, ask events negative, handling price-up / price-down / price-same cases per the paper). Scatter vs `Δmid_{t+1}` with OLS regression. Reports **Kyle's λ** (slope = price impact per unit flow) per product.

### Tab: MM Alpha (enables when trades have non-empty buyer/seller)

The market-making alpha core.

- **Mark-out by counterparty** ⭐⭐ — for each (counterparty, side), the mean `mid(t+Δ) − price` (buyers) / `price − mid(t+Δ)` (sellers) at Δ = 1, 5, 10, 50 ticks. Sorted by |Δ=50 mark-out|. The Signal column labels each row:
  - `INFORMED` / `toxic` (red/orange) = they profited from trading, their fills hurt a maker — **avoid quoting into them**.
  - `DUMB` / `dumb` (teal/green) = they lost — **exactly who you want to trade**.
  - This is _the_ Prosperity alpha. In P3 R5 you can read the personalities off the table: Caesar, Paris, Charlie, Olivia, etc.
- **Effective vs realized spread** — Lee-Ready classification (aggressor = sign of `price − mid`), then:
  - `effective = 2·|price − mid_t|` — taker round-trip cost.
  - `realized = 2·sign·(price − mid_{t+10})` — maker gross edge after a 10-tick carry.
  - `adverse selection = effective − realized` — what the maker lost to informed flow.
  - Plus `mean sign` (positive ⇒ buyer-initiated tape).
- **Trade offset from mid, by counterparty** — distribution of `price − mid` (for buyers; sign-flipped for sellers so positive always = trading above mid). Tells you who lifts aggressively (positive offset) vs who passively rests inside the spread.

### Tab: Cross-Asset (enables with ≥ 2 products)

Multi-product alpha setups.

- **Return correlation matrix** — Highcharts heatmap of per-tick return Pearson correlations. Red = co-move, blue = diverge. Merge-join per-product timestamps, so cells are real sample-overlap, not dense-grid interpolation. Null cells (no overlap) render dark grey with `n=0` in tooltip; cell tooltip shows `corr` + `n` samples.
- **Lead-lag CCF** — pair picker + bar chart of `corr(ΔA_t, ΔB_{t+lag})` at lags ±20 steps. Positive lag = A leads B by that many ticks. The tallest bar is the most-useful lead/lag relationship; the panel reports best-lag and its correlation explicitly.
- **Pair spread + z-score** — OLS `mid_A ≈ α + β·mid_B`, plots the residual time series and its rolling z-score with ±2σ bands. Reports:
  - **β** (hedge ratio)
  - **R²** (co-movement strength)
  - **OU half-life** (rows) — fit `Δr_t = a + b·r_t`; if `b < 0`, half-life `= −ln 2 / ln(1+b)`. Finite ⇒ the spread actually reverts ⇒ basket arb is real. Infinite = no reversion, not a pair.
  - Directly usable on Prosperity basket products (PICNIC_BASKET1/2 vs CROISSANTS/JAMS/DJEMBES).

### Tab: Exogenous (enables when an `observations_*.csv` exists)

Observations are conversion-product driver columns (tariffs, transport fees, sugar price, sunlight index, etc.) joined to the prices tape.

- **Observation time series** — one auto-generated line chart per numeric observation column. Works for any schema — if IMC adds new observation columns in future rounds, they just appear.
- **Observation → product return β** — for each (observation column × product) pair, fits `Δmid_{t+lag} = α + β·obs_t` by OLS (binary-searched per-product price index for the join). Lag selector 100/500/1000/5000 timestamp units. Table sorted by |correlation|. Large |β| with high R² at useful lag = exogenous alpha you can trade on (e.g. sunlight → MAGNIFICENT_MACARONS in P3 R4-R5).

### Tab: Seasonality (always enabled with prices)

Intraday patterns.

- **Mean spread by intraday bucket** — timestamps wrapped via `timestamp mod dayPeriod` (default 200 000 = Prosperity's 2000 ticks × 100 grid), split into 20 buckets. Shows per-product mean `ask1 − bid1` per bucket.
- **Return volatility by intraday bucket** — same buckets, RMS `Δmid`. Reveals systematic vol regimes within the trading day.

### Tab: Trades (enables when a trades file exists)

- Full trade tape rendered with **mantine-react-table** — filterable / sortable / virtualized, adapts automatically to whatever columns the file has.

### Tab: Counterparty (enables when trades exist)

- Pivot of trades per (counterparty, side): trade count, qty, notional, VWAP, avg price. Sorted by trade volume.

### Tab: Schema

- Introspected column types for the loaded files (prices, trades, observations, other), with detected-kind badges (`time`, `product`, `counterparty`, `numeric`, `categorical`). Shows how many products / counterparties / ladder levels were detected. Essential for debugging odd data.

---

## Which rounds fire which tabs

| Round     | Overview | LOB | MM Alpha |   Cross-Asset    | Exogenous | Seasonality | Trades |
| --------- | :------: | :-: | :------: | :--------------: | :-------: | :---------: | :----: |
| P3 R1     |    ✅    | ✅  |    ❌    | ✅ (3 products)  |    ❌     |     ✅      |   ✅   |
| P3 R2     |    ✅    | ✅  |    ❌    |        ✅        |    ❌     |     ✅      |   ✅   |
| P3 R3     |    ✅    | ✅  |    ❌    |        ✅        |    ❌     |     ✅      |   ✅   |
| P3 R4     |    ✅    | ✅  |    ❌    |        ✅        |    ✅     |     ✅      |   ✅   |
| **P3 R5** |    ✅    | ✅  |  **✅**  |        ✅        |    ✅     |     ✅      |   ✅   |
| P3 R6     |    ✅    | ✅  |    ❌    |        ✅        |    ❌     |     ✅      |   ✅   |
| P3 R7     |    ✅    | ✅  |    ❌    | ✅ (15 products) |    ❌     |     ✅      |   ❌   |
| P3 R8     |    ✅    | ✅  |    ❌    |        ✅        |    ❌     |     ✅      |   ✅   |
| P4 R0–R2  |    ✅    | ✅  |    ❌    | ✅ (2 products)  |    ❌     |     ✅      |   ✅   |

**P3 R5** is the one round with everything. Named bot counterparties in the tape unlock MM Alpha; observations unlock Exogenous; 16 products (RAINFOREST_RESIN, KELP, SQUID_INK, CROISSANTS, JAMS, DJEMBES, PICNIC_BASKET1/2, VOLCANIC_ROCK + 5 vouchers, MAGNIFICENT_MACARONS) make Cross-Asset interesting.

---

## Architecture

```
Browser (main thread)
  ┌──────────────────────────────────────────────────────────┐
  │ React/Vite UI                                             │
  │  • Mantine 7 + Highcharts 11 (+ Boost, + Heatmap module)  │
  │  • WorkshopPage.tsx loads files, hoists projection once   │
  │  • Panels dispatch typed tasks via useCompute(task)       │
  └────────────────────────┬─────────────────────────────────┘
                           │ structuredClone task
                           ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Web Worker (compute/worker.ts)                            │
  │  • Hosts single WASM instance (init once, reused)         │
  │  • Dispatches to wasm_compute functions                   │
  └────────────────────────┬─────────────────────────────────┘
                           │ Float64Array → wasm linear memory
                           ▼
  ┌──────────────────────────────────────────────────────────┐
  │ wasm_compute (Rust)                                       │
  │  • opt-level=3 + LTO=fat + panic=abort                    │
  │  • 13 kernels: mid, spread, depth, queueImbalance, ofi,   │
  │    markout, offset, effRealized, corrMatrix, leadLag,     │
  │    pairSpread, obsBeta, seasonality                       │
  │  • Per-product sorted (time, mid) index + binary-search   │
  │    for trade × price joins                                │
  │  • Two-pointer merge-join for pairwise correlations       │
  └──────────────────────────────────────────────────────────┘
                           ▲
                           │ HTTP (via Vite proxy port 5555 → 8001)
                           │
  ┌──────────────────────────────────────────────────────────┐
  │ Python data server (backtester/dashboard_server.py)      │
  │  • GET /__prosperity4mcbt__/workshop/tree → file list     │
  │  • GET /__prosperity4mcbt__/workshop/file?path=… → CSV    │
  │  • Path-traversal guarded                                 │
  └──────────────────────────────────────────────────────────┘
```

### Key frontend files

```
visualizer/src/pages/workshop/
├── WorkshopPage.tsx          # top-level shell, data selector, tab layout
├── loader.ts                 # CSV fetch + papaparse (worker mode) + caching
├── schema.ts                 # column-kind inference, ladder detection (regex)
├── concat.ts                 # multi-day concat with cumulative tick key
├── types.ts                  # frontend types
├── compute/
│   ├── worker.ts             # Web Worker: WASM init + task dispatch
│   ├── useCompute.ts         # React hook: cancellation-aware, keeps last result
│   ├── project.ts            # PreparedPrices / PreparedTrades (hoisted once)
│   ├── types.ts              # task input/output types (parallel to Rust structs)
│   └── kernels.ts            # fallback TS kernels (unused; kept as reference)
└── panels/
    ├── MidPricePanel.tsx, SpreadPanel.tsx                  # Overview
    ├── DepthAreaPanel.tsx, QueueImbalancePanel.tsx, OfiPanel.tsx   # LOB
    ├── MarkoutPanel.tsx, EffRealizedPanel.tsx, OffsetFromMidPanel.tsx  # MM Alpha
    ├── CorrMatrixPanel.tsx, LeadLagPanel.tsx, PairSpreadPanel.tsx   # Cross-Asset
    ├── ObservationsLinesPanel.tsx, ObsBetaPanel.tsx        # Exogenous
    ├── SeasonalityPanel.tsx                                # Seasonality
    ├── TradeTape.tsx, CounterpartyPivot.tsx                # Trades / Counterparty
    └── SchemaCard.tsx                                      # Schema
```

### Rust crate

```
wasm_compute/
├── Cargo.toml                # opt-level=3, lto=fat, wasm-bindgen, serde-wasm-bindgen
└── src/lib.rs                # all 13 kernels, single file ~900 lines
```

Built output lands at `visualizer/wasm_compute/` (gitignored). The build step is automatic in `run.ps1` / `run.sh`:

```powershell
# only rebuilds when wasm_compute/src/lib.rs is newer than the built .wasm
wasm-pack build --release --target web --out-dir ../visualizer/wasm_compute
```

### Adaptivity

Nothing in the Workshop hardcodes product names, schema shapes, or column names:

- Ladder levels detected via regex `(bid|ask)_(price|volume)_\d+` — works for any depth.
- Mid column detected by case-insensitive name match (`mid_price`, `mid`, `midprice`).
- CSV delimiter auto-detected (`;` for prices/trades, `,` for observations).
- Trade tape renders **every column** the file has, so future P4 rounds with new fields just work.
- Observations auto-line chart iterates whatever numeric columns are present.
- Tabs disable themselves when their required data isn't in the loaded files.

Worst case when IMC adds a new round with a new schema: the Schema tab still shows everything, and the generic panels (Trade tape, Observations auto-lines) still render. Specific new panels can be added to `panels/` later.

---

## Performance notes

For the biggest round we have (P3 R7, 580 k rows × 15 products, "all days" concat):

- CSV parse: ~300 ms (off main thread via PapaParse worker mode).
- Projection: ~80 ms (hoisted to WorkshopPage; panels share one result).
- Per-panel compute: 5–50 ms in WASM.
- Total visible freeze from switching tabs or products: **none** — tabs are `keepMounted`, compute runs in the worker, Highcharts boost handles dense scatter via canvas/WebGL, dense scatter markers have `enableMouseTracking: false` so hover doesn't hit-test thousands of points.

If you see a freeze, the first thing to check is the Schema tab — unusually-shaped data (e.g. a column that looks numeric but isn't) sometimes forces a fallback path.

---

## Troubleshooting

### "Failed to load data tree" / 404 on Workshop tab

The Python data server isn't running or isn't serving the workshop endpoints. Check `tmp/backtests/dashboard_server.log`. Usually fixed by re-running `./run.ps1` / `./run.sh` (they force-kill stale :8001 listeners at start-up).

### Heatmap cells only painting on hover

You're running an old cached bundle. Hard-refresh the tab (Ctrl-Shift-R / Cmd-Shift-R). If it persists, delete `visualizer/node_modules/.vite/` and re-run.

### "wasm-pack failed" on start

Check `tmp/backtests/wasm_build.log`. Common cause: stale `wasm_compute/Cargo.lock` after Rust update (`rm wasm_compute/Cargo.lock` and re-run).

### Workshop tabs all disabled

The round might be missing required files. Open the **Schema** tab — if it says "Not loaded for the current selection" for prices, the CSV didn't parse. Check the file exists and has the expected headers.

### "No backtests yet" on Results tab

Unrelated to Workshop — the MC dashboard just hasn't been populated. Run `prosperity4mcbt traders/round3/a.py --quick` from a terminal or use the Run tab.

---

## References

- Stoikov microprice: Stoikov, S. (2018). _The Micro-Price: A High-Frequency Estimator of Future Prices_.
- Queue imbalance as alpha: Cartea, Á., Jaimungal, S. (2015). _Enhancing trading strategies with order book signals_.
- OFI: Cont, R., Kukanov, A., Stoikov, S. (2014). _The price impact of order book events_.
- Kyle's λ: Kyle, A.S. (1985). _Continuous Auctions and Insider Trading_.
- Lee-Ready classification: Lee, C.M.C., Ready, M.J. (1991). _Inferring Trade Direction from Intraday Data_.
- Effective / realized spread decomposition: Hasbrouck, J. (2007). _Empirical Market Microstructure_.
- Pair trading / OU half-life: Engle, R., Granger, C.W.J. (1987). _Co-integration and Error Correction_.
