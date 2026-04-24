"""Generate Rust AssetSim modules for the 12 R3 products.

Reads each `calibration/<asset>/params.json` + the trade history from
`fv_and_book.json` to derive trade probabilities, and emits a self-contained
.rs module under `rust_simulator/src/assets/<asset>.rs`.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO / "rust_simulator" / "src" / "assets"

R3_ASSETS = [
    "hydrogel_pack",
    "velvetfruit_extract",
    "vev_4000", "vev_4500", "vev_5000", "vev_5100",
    "vev_5200", "vev_5300", "vev_5400", "vev_5500",
    "vev_6000", "vev_6500",
]

# Per-product position limits (R3 — confirmed against the portal product page).
# HYDROGEL/VELVET = 200, each VEV voucher = 300. Used to override the
# `position_limit` field in params.json (which Stage 8 fills with a default 80).
R3_POSITION_LIMITS = {
    "hydrogel_pack": 200,
    "velvetfruit_extract": 200,
    "vev_4000": 300, "vev_4500": 300, "vev_5000": 300, "vev_5100": 300,
    "vev_5200": 300, "vev_5300": 300, "vev_5400": 300, "vev_5500": 300,
    "vev_6000": 300, "vev_6500": 300,
}

# Per-product ELASTIC trade-rate overrides — back-fitted from portal sub 366383
# (penny-jump MM at portal-UI scale, day 2). The raw R3 trade CSVs only capture
# bot↔bot trades from a recording where no aggressive MM was active; once we
# show up with an improved quote, real elastic takers fire much more often
# than the CSV would suggest, especially on wide-spread products.
#
# Methodology: for each asset, run a heavy MC at 1k ticks/day with the default
# heuristic, observe sim PnL vs portal, then scale elastic up by the PnL ratio.
# Iterate until sim mean PnL is within ~30% of portal at the same scale.
#
# When None or missing, fall back to the heuristic in `_trade_rates`.
R3_ELASTIC_OVERRIDES: dict = {
    # Spot products — observed portal PnL @ 1k ticks: 569 / 429
    "hydrogel_pack":       0.020,
    "velvetfruit_extract": 0.053,
    # Deep-ITM call — observed portal PnL: 134
    "vev_4000":            0.007,
    # ITM/ATM strikes — bootstrap from portal PnL since CSVs say ~0 trades.
    # Spreads taper: 16 / 6 / 4 / 3 -> elastic decays similarly.
    "vev_4500":            0.013,
    "vev_5000":            0.010,
    "vev_5100":            0.015,
    "vev_5200":            0.003,
    # Deep-OTM (sub-cent FV) — portal showed 0 PnL; no point quoting.
    "vev_5300":            0.0005,
    "vev_5400":            0.0,
    "vev_5500":            0.0,
    "vev_6000":            0.0,
    "vev_6500":            0.0,
}


def _formula_expr(spec: dict, side: str) -> str:
    """Render formula_spec → Rust expression returning i32, given variable `fair: f64`."""
    rnd = spec["round_fn"]
    K = spec.get("K")
    if K is not None:
        sign = "-" if side == "bid" else "+"
        inner = f"fair * (1.0 {sign} {K!r})"
        if rnd == "floor":
            return f"({inner}).floor() as i32"
        if rnd == "ceil":
            return f"({inner}).ceil() as i32"
        # banker's rounding — Rust f64::round rounds half away from zero, not banker's.
        # Use a custom helper to match the kernel's round_half_to_even.
        return f"banker_round({inner}) as i32"
    # Fixed
    shift = float(spec.get("shift", 0.0))
    constant = int(spec.get("constant", 0))
    if abs(shift) < 1e-12:
        inner = "fair"
    else:
        op = "+" if shift >= 0 else "-"
        inner = f"(fair {op} {abs(shift)!r})"
    if rnd == "floor":
        base = f"{inner}.floor() as i32"
    elif rnd == "ceil":
        base = f"{inner}.ceil() as i32"
    else:
        base = f"banker_round({inner}) as i32"
    if constant == 0:
        return base
    op = "+" if constant >= 0 else "-"
    return f"{base} {op} {abs(constant)}"


def _sim_fv_body(fv_proc: dict) -> str:
    typ = fv_proc["type"]
    p = fv_proc["params"]
    if typ == "random_walk":
        sigma = p.get("sigma", 0.0)
        drift = p.get("drift", 0.0)
        mean = p.get("mean", 0.0)
        return f"""        let sigma: f64 = {sigma!r};
        let drift: f64 = {drift!r};
        let mean: f64 = {mean!r};
        let mut values = Vec::with_capacity(ticks);
        if ticks == 0 {{ return Ok(values); }}
        // Start at mean for day 0; otherwise we'd want a continuous chain across days,
        // but R3 calibration is per-day-2 hold-1, so each day starts independently.
        values.push(mean);
        for _ in 1..ticks {{
            let step = drift + sigma * sample_standard_normal(rng);
            values.push(values[values.len() - 1] + step);
        }}
        Ok(values)"""
    if typ == "linear_drift":
        sigma = p.get("sigma", 0.0)
        drift = p.get("drift", 0.0)
        mean = p.get("mean", 0.0)
        return f"""        let sigma: f64 = {sigma!r};
        let drift: f64 = {drift!r};
        let mean: f64 = {mean!r};
        let mut values = Vec::with_capacity(ticks);
        for tick in 0..ticks {{
            let total_tick = day_index * ticks + tick;
            let level = mean + (total_tick as f64) * drift + sigma * sample_standard_normal(rng);
            values.push(level);
        }}
        Ok(values)"""
    if typ == "constant":
        sigma = p.get("sigma", 0.0)
        mean = p.get("mean", 0.0)
        return f"""        let mean: f64 = {mean!r};
        let sigma: f64 = {sigma!r};
        let mut values = Vec::with_capacity(ticks);
        for _ in 0..ticks {{
            values.push(mean + sigma * sample_standard_normal(rng));
        }}
        Ok(values)"""
    if typ == "ar1":
        sigma = p.get("sigma", 0.0)
        drift = p.get("drift", 0.0)
        ar1 = p.get("ar1_coef", 0.0)
        return f"""        let sigma: f64 = {sigma!r};
        let drift: f64 = {drift!r};
        let ar1: f64 = {ar1!r};
        let mut values = Vec::with_capacity(ticks);
        if ticks == 0 {{ return Ok(values); }}
        values.push(0.0);
        let mut prev_step = drift;
        for _ in 1..ticks {{
            let step = drift + ar1 * (prev_step - drift) + sigma * sample_standard_normal(rng);
            values.push(values[values.len() - 1] + step);
            prev_step = step;
        }}
        Ok(values)"""
    raise ValueError(f"unsupported FV process type: {typ}")


def _make_book_body(bots: list) -> str:
    """Render Bot quotes given fair: f64 + rng. Each bot can be deterministic, iid_bernoulli, joint_empirical."""
    lines = [
        "        let mut bids: Vec<(i32, i32)> = Vec::new();",
        "        let mut asks: Vec<(i32, i32)> = Vec::new();",
    ]
    for i, bot in enumerate(bots, 1):
        bid_expr = _formula_expr(bot["formula_spec"]["bid"], "bid")
        ask_expr = _formula_expr(bot["formula_spec"]["ask"], "ask")
        pres = bot["presence"]
        bid_rate = pres.get("bid_rate", pres.get("rate", 0.8))
        ask_rate = pres.get("ask_rate", pres.get("rate", 0.8))
        vol = bot["volume"]
        # Volume sampler: uniform or empirical.
        if vol["distribution"] == "uniform":
            lo = int(vol["low"]); hi = int(vol["high"])
            vol_sample = f"rng.gen_range({lo}..={hi})"
        else:
            # empirical: sample from PMF stored in params.
            pmf = vol.get("pmf") or {}
            keys = sorted(int(k) for k in pmf.keys())
            weights = [int(round(pmf[str(k)] * 1000)) for k in keys]
            if not keys or sum(weights) == 0:
                # Fallback: U(low, high)
                lo = int(vol["low"]); hi = int(vol["high"])
                vol_sample = f"rng.gen_range({lo}..={hi})"
            else:
                vals_arr = "[" + ", ".join(str(k) for k in keys) + "]"
                w_arr = "[" + ", ".join(str(w) for w in weights) + "]"
                vol_sample = f"sample_weighted(&{vals_arr}, &{w_arr}, rng)"
        sides_tied = vol.get("sides_tied", False)
        lines.append(f"        // Bot {i}: bid_rate={bid_rate:.3f} ask_rate={ask_rate:.3f}  sides_tied={sides_tied}")
        # Sample volume(s)
        if sides_tied:
            lines.append(f"        let v{i} = {vol_sample};")
            v_bid = v_ask = f"v{i}"
        else:
            lines.append(f"        let v{i}_bid = {vol_sample};")
            lines.append(f"        let v{i}_ask = {vol_sample};")
            v_bid = f"v{i}_bid"; v_ask = f"v{i}_ask"
        # Presence
        lines.append(f"        if rng.gen_bool({bid_rate}) {{ bids.push(({bid_expr}, {v_bid})); }}")
        lines.append(f"        if rng.gen_bool({ask_rate}) {{ asks.push(({ask_expr}, {v_ask})); }}")
    lines += [
        "        bids.sort_by(|a, b| b.0.cmp(&a.0));",
        "        asks.sort_by(|a, b| a.0.cmp(&b.0));",
        "        Book { bids, asks }",
    ]
    return "\n".join(lines)


def _trade_qty_body(trades: list) -> str:
    if not trades:
        return "        volume_limit.max(1)"
    qtys = Counter(t["quantity"] for t in trades)
    keys = sorted(qtys)
    weights = [qtys[k] for k in keys]
    vals_str = ", ".join(str(k) for k in keys)
    w_str = ", ".join(str(w) for w in weights)
    return f"""        let _ = market_buy;
        let values: &[i32] = &[{vals_str}];
        let weights: &[u32] = &[{w_str}];
        let filtered: Vec<(i32, u32)> = values.iter().zip(weights.iter())
            .filter(|(v, _)| **v <= volume_limit).map(|(v, w)| (*v, *w)).collect();
        if filtered.is_empty() {{ return volume_limit.max(1); }}
        let vals: Vec<i32> = filtered.iter().map(|(v, _)| *v).collect();
        let ws: Vec<u32> = filtered.iter().map(|(_, w)| *w).collect();
        let chooser = WeightedIndex::new(ws).expect(\"valid trade weights\");
        vals[chooser.sample(rng)]"""


def _trade_rates(trades: list, n_ticks: int) -> dict:
    """Compute trade probabilities from observed market trades.

    The R3 trade CSVs (data/prosperity4/round3/trades_round_3_day_{0,1,2}.csv)
    each cover one full final-eval day = 10,000 ticks. n_ticks here is the
    number of FV ticks from the hold-1 sub (1,000 = portal-UI scale) and is
    NOT the trade-CSV horizon. Use the CSV total directly, not 3 * n_ticks.
    """
    if not trades:
        return {"base": 0.0, "second": 0.0, "elastic": 0.0}
    # Per-tick counts, segmented by source so we don't collide ts buckets across days.
    per_day_ticks: dict = {}
    for t in trades:
        src = t.get("source", "_")
        b = (int(t["ts"]) // 100) * 100
        per_day_ticks.setdefault(src, {})
        per_day_ticks[src][b] = per_day_ticks[src].get(b, 0) + 1
    n_days = len(per_day_ticks) if per_day_ticks else 1
    # Final-eval day = 10,000 ticks; the CSVs run end-to-end at that scale.
    TICKS_PER_CSV_DAY = 10_000
    n_total_ticks = n_days * TICKS_PER_CSV_DAY
    n_ticks_with_trade = sum(len(d) for d in per_day_ticks.values())
    base = n_ticks_with_trade / max(1, n_total_ticks)
    multi = sum(c - 1 for d in per_day_ticks.values() for c in d.values() if c > 1)
    second = multi / max(1, n_ticks_with_trade)
    # Elastic = takers that act AFTER the strategy (and so can fill our improved
    # quotes). The raw market-trade CSV doesn't separate these from base takers,
    # so use the OSMIUM/PEPPER calibrated ratio (~base * 0.25) as a starting
    # point. This may need per-asset tuning against portal logs.
    return {"base": base, "second": second, "elastic": base * 0.25}


HEADER_TEMPLATE = '''//! {symbol} — Round 3 product.
//!
//! Auto-generated by `tmp/generate_r3_asset_rs.py` from
//! `calibration/{snake}/params.json`. Edit the params file and re-run the
//! generator instead of editing this file by hand.
//!
//! Trade rates: BASE / SECOND derived from R3 trade CSVs (3 days × 10K ticks).
//! ELASTIC back-fitted against portal sub 366383 (penny-jump MM at 1K ticks);
//! see R3_ELASTIC_OVERRIDES in the generator. Method: scale until sim mean
//! PnL is within ~1σ of the portal sample for that asset.
//!
//! Calibration: see `calibration/{snake}/calibration.md`.
'''


CODE_TEMPLATE = '''
use crate::asset::{{
    AssetSim, Book, FlagKind, FlagSpec, load_replay_fv_path, parse_path, sample_standard_normal,
}};
use anyhow::Result;
use rand::distributions::{{Distribution, WeightedIndex}};
use rand::Rng;
use rand_chacha::ChaCha8Rng;
use std::collections::HashMap;

pub const SYMBOL: &str = "{symbol}";

const POSITION_LIMIT: i32 = {position_limit};
const BASE_TRADE_PROB: f64 = {base_trade_prob!r};
const SECOND_TRADE_PROB: f64 = {second_trade_prob!r};
const ELASTIC_TRADE_PROB: f64 = {elastic_trade_prob!r};
const BUY_PROB: f64 = 0.5;

pub struct {struct_name} {{
    replay_fv: Option<Vec<f64>>,
}}

pub fn flag_specs() -> Vec<FlagSpec> {{
    vec![FlagSpec {{
        name: "replay-fv",
        kind: FlagKind::Path,
        default: None,
        help: "Replay observed FV (JSON: flat [f64] or object with '{snake}' key)",
    }}]
}}

pub fn build(flags: &HashMap<String, String>) -> Result<Box<dyn AssetSim>> {{
    let replay_fv = match flags.get("replay-fv") {{
        Some(raw) => {{
            let path = parse_path("{kebab}-replay-fv", raw)?;
            Some(load_replay_fv_path(&path, "{snake}")?)
        }}
        None => None,
    }};
    Ok(Box::new({struct_name} {{ replay_fv }}))
}}

/// Banker's rounding (round half to even) — matches the calibration kernel
/// and the Rust formula_search; differs from f64::round which rounds half away from 0.
fn banker_round(x: f64) -> i64 {{
    let f = x.floor();
    let frac = x - f;
    if frac > 0.5 {{ (f as i64) + 1 }}
    else if frac < 0.5 {{ f as i64 }}
    else {{
        let fi = f as i64;
        if fi % 2 == 0 {{ fi }} else {{ fi + 1 }}
    }}
}}

fn sample_weighted(values: &[i32], weights: &[u32], rng: &mut ChaCha8Rng) -> i32 {{
    let chooser = WeightedIndex::new(weights).expect("valid weights");
    values[chooser.sample(rng)]
}}

impl AssetSim for {struct_name} {{
    fn symbol(&self) -> &str {{
        SYMBOL
    }}

    fn position_limit(&self) -> i32 {{
        POSITION_LIMIT
    }}

    fn simulate_fv(
        &self,
        day_index: usize,
        ticks: usize,
        rng: &mut ChaCha8Rng,
    ) -> Result<Vec<f64>> {{
        if let Some(observed) = &self.replay_fv {{
            let mut out = Vec::with_capacity(ticks);
            for i in 0..ticks {{
                out.push(observed[i.min(observed.len().saturating_sub(1))]);
            }}
            return Ok(out);
        }}
        let _ = day_index;
{simulate_fv_body}
    }}

    fn make_book(&self, fair: f64, rng: &mut ChaCha8Rng) -> Book {{
{make_book_body}
    }}

    fn base_trade_prob(&self) -> f64 {{
        BASE_TRADE_PROB
    }}

    fn second_trade_prob(&self) -> f64 {{
        SECOND_TRADE_PROB
    }}

    fn elastic_trade_prob(&self) -> f64 {{
        ELASTIC_TRADE_PROB
    }}

    fn buy_prob(&self) -> f64 {{
        BUY_PROB
    }}

    fn sample_trade_qty(
        &self,
        market_buy: bool,
        volume_limit: i32,
        rng: &mut ChaCha8Rng,
    ) -> i32 {{
{trade_qty_body}
    }}
}}
'''


def to_pascal(snake: str) -> str:
    return "".join(p.capitalize() for p in snake.split("_"))


def generate(asset: str) -> str:
    pj = REPO / "calibration" / asset / "params.json"
    fb = REPO / "calibration" / asset / "data" / "fv_and_book.json"
    p = json.loads(pj.read_text())
    data = json.loads(fb.read_text())
    n_ticks = sum(1 for r in data["rows"] if r.get("fv") is not None)
    trades = data.get("trades", []) or []
    rates = _trade_rates(trades, n_ticks)
    if asset in R3_ELASTIC_OVERRIDES:
        rates["elastic"] = R3_ELASTIC_OVERRIDES[asset]
    symbol = p["asset"]
    snake = asset
    kebab = snake.replace("_", "-")
    struct_name = to_pascal(snake)
    body = HEADER_TEMPLATE.format(symbol=symbol, snake=snake) + CODE_TEMPLATE.format(
        symbol=symbol,
        snake=snake,
        kebab=kebab,
        struct_name=struct_name,
        position_limit=R3_POSITION_LIMITS.get(asset, p.get("position_limit", 80)),
        base_trade_prob=rates["base"],
        second_trade_prob=rates["second"],
        elastic_trade_prob=rates["elastic"],
        simulate_fv_body=_sim_fv_body(p["fv_process"]),
        make_book_body=_make_book_body(p["bots"]),
        trade_qty_body=_trade_qty_body(trades),
    )
    return body


def main() -> int:
    for asset in R3_ASSETS:
        try:
            rs = generate(asset)
        except Exception as e:
            print(f"  ! {asset} FAILED: {e}")
            continue
        out = ASSETS_DIR / f"{asset}.rs"
        out.write_text(rs, encoding="utf-8")
        print(f"  + {out.relative_to(REPO)} ({len(rs)} bytes)")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
