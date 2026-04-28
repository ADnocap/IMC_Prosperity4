# R5 MC sim — design doc

## Goal

The R3/R4 sim generates 1 FV path + 1 Poisson trade process *per asset, independent*. R5's structural findings (FINDINGS_v2.md) make that wrong:

- 50 FVs are not independent — Pebbles satisfies `sum=50,000`, Snackpacks have a CHOC+VANILLA pair + a 3-asset triplet constraint.
- Trades come in **3 shared pulse processes** (Vanilla / Pebbles / Microchips), not 50 independent Poissons.
- All FVs are bounded (OU-like), not free random walks.

The new sim must respect these as first-class invariants. If the constraints don't hold *exactly* in the synthetic data, basket-arb strategies will look profitable in MC and lose money in production (or vice versa).

## Current architecture (R3/R4)

```
main.rs::generate_day(day):
  for asset in active_assets:
    fv[asset] = asset.simulate_fv(day, ticks, rng)         # per-asset RW
    trade_counts[asset] = trade_counts_for(asset, ...)     # per-asset Poisson
  for tick in 0..ticks:
    for asset in active_assets:
      book = asset.make_book(fv[asset][tick], rng)         # symmetric around FV
      apply_quote_fraction(book, ...)
      n = trade_counts[asset][tick]
      for _ in 0..n: sample_trade_rows(asset, book, rng)   # per-asset trade
```

Per-asset RW + per-asset Poisson = independence baked in at the lowest level. To support R5 we need a layer above the asset that generates joint state.

## Proposed architecture (R5)

Introduce a `Scenario` abstraction that owns the *joint* state and emits per-asset materialised paths. Existing `AssetSim` stays for book generation and per-asset bot params; the scenario takes over FV generation and trade-event generation.

```
trait Scenario {
    fn generate_session(
        &self, days: &[i32], ticks: usize, rng: &mut ChaCha8Rng
    ) -> SessionData;
}

struct SessionData {
    fv_paths: HashMap<(String, i32), Vec<f64>>,    // (symbol, day) → 10K FVs
    pulses_per_day: HashMap<i32, Vec<Pulse>>,      // day → list of pulses
}

struct Pulse {
    tick: usize,                                   // when in the day
    members: Vec<String>,                          // which products fire
    direction: Direction,                          // Buy or Sell
    quantity: i32,                                 // shared across members
}
```

`generate_day` becomes:

```
generate_day(day, scenario, ...):
  session = scenario.generate_session(...)         # done once at session start
  for tick in 0..ticks:
    for asset in active_assets:
      book = asset.make_book(session.fv_paths[(symbol, day)][tick], rng)
      ...
      // (bot pulses replace per-asset trades)
    for pulse in session.pulses_per_day[day] where pulse.tick == tick:
      for member in pulse.members:
        execute_pulse_against_book(member, pulse.direction, pulse.quantity)
```

### Two scenarios

| Scenario | FV process | Trade process | When |
| --- | --- | --- | --- |
| `IndependentScenario` | per-asset RW (delegates to `AssetSim::simulate_fv`) | per-asset Poisson (existing `trade_counts_for`) | R1-R4 backward compat |
| `R5Scenario` | joint OU + constraints | 3 shared Poisson pulse processes | R5 |

Scenario is selected from CLI flag or auto-detected from active products (if trader declares R5 products → R5Scenario).

## R5Scenario internals

### FV generation

State (per session):
- 50 OU-process FVs `F[asset]`
- 1 latent K_day for CHOC+VANILLA pair (slow walk)
- 3 latent factors driving the snackpack triplet (PIS / STRAW / RASP) under their constraint

Per-tick advance:

1. **Independent OU steps** for the 47 free DoF:
   - 35 vanilla products outside constraints (5 robots, 5 sleep_pods, 5 translators, 5 panels, 5 oxygen_shakes, 5 galaxy_sounds, 5 uv_visors)
   - 4 free pebbles (XS, S, M, L)
   - 2 snackpack DoF (e.g. CHOC + a third snackpack walk)
   - 5 microchips
   - K_day walk
   
   Each OU step: `F[i] += -θ_i × (F[i] - μ_i) + σ_i × N(0,1)`, snapped to half-integer.

2. **Derived FVs** (constrained):
   - `mid_PEBBLES_XL = round(50_000 - sum(other 4 pebbles), 0.5)`
   - `mid_VANILLA_SNACK = round(K_day - mid_CHOCOLATE, 0.5)`
   - Snackpack triplet residual handled via 2 free + 1 derived (or 3 correlated walks — TBD by fit pass)

3. **Daily resampling** at day boundaries:
   - `μ_i` for OU is resampled per day (each day has its own mean)
   - K_day starts from K_{day-1} + drift (slow random walk)

Parameters per asset (`σ_i, θ_i, μ_i, h_i, depth_L1, depth_L2`) live in a YAML/JSON config under `calibration/r5/scenario_params.json`, fitted from historical CSVs.

### Trade pulse generation

Three independent Poisson processes:

```
struct PulseProcess {
    rate_per_tick: f64,         // λ
    members: Vec<String>,       // which products fire together
    qty_dist: QtyDist,          // discrete uniform over a range
    direction_p_buy: f64,       // 0.5
}

fn sample_pulses(processes: &[PulseProcess], ticks: usize, rng: &mut ChaCha8Rng) -> Vec<Pulse> {
    let mut out = Vec::new();
    for tick in 0..ticks {
        for proc in processes {
            if rng.gen::<f64>() < proc.rate_per_tick {
                out.push(Pulse {
                    tick,
                    members: proc.members.clone(),
                    direction: if rng.gen::<f64>() < proc.direction_p_buy { Buy } else { Sell },
                    quantity: proc.qty_dist.sample(rng),
                });
            }
        }
    }
    out
}
```

Calibrated rates from FINDINGS_v2:
- V (40 products): λ ≈ 244 / 10000 = **0.0244 per tick**, qty ∈ Uniform{1,2,3,4}
- P (5 pebbles): λ ≈ 215 / 10000 = **0.0215 per tick**, qty ∈ Uniform{2,3,4,5}
- M (5 microchips): λ ≈ 190 / 10000 = **0.0190 per tick**, qty ∈ Uniform{1,2,3}

The 2% cross-pulse overlap rate is exactly what independent Bernoulli(p=0.02) gives, confirming independent processes.

### Pulse execution

Each pulse, for each member:
- Direction = Sell → take qty units from the book at `bid_price_1` (or sweep into L2 if L1 has < qty depth — based on the 1.5% multi-qty pulses, this happens occasionally)
- Direction = Buy → take qty units from the book at `ask_price_1` (similarly)

If the strategy is also quoting at L1, the pulse pro-rata fills against the bot's book first or the strategy's quotes — depending on time-priority + LevelOwner. The current main.rs already supports `LevelOwner::Bot` vs `LevelOwner::Strategy`, so we just need to route pulses through `apply_take_against_book`.

## Migration plan

### Phase 1 — non-invasive: add `Scenario` abstraction
- Define `Scenario` trait + `SessionData` types in `src/scenario.rs`
- Wrap existing per-asset logic in `IndependentScenario` (R1-R4 path)
- Plumb through main.rs: `Config` gains a `scenario: Box<dyn Scenario>` field; `generate_day` reads from `SessionData`
- All R3/R4 backtests continue to work bit-identical (use `IndependentScenario` by default)

### Phase 2 — implement `R5Scenario`
- New `src/scenarios/r5.rs` implementing the joint state, OU walks, constraint derivation, pulse generation
- Calibration JSON loaded from `calibration/r5/scenario_params.json`
- Feature flag: `--scenario r5` switches the scenario; auto-detect via R5 product symbols in the trader

### Phase 3 — R5 asset modules (parametrised, not 50 boilerplate files)
- `src/assets/vanilla.rs` — parameterised by `(symbol, h, depth_l1, depth_l2)`, used for the 40 vanilla products
- `src/assets/pebble.rs` — same, for 5 pebbles  
- `src/assets/microchip.rs` — same, for 5 microchips
- Registry in `assets/mod.rs` maps each of 50 R5 product symbols → (`AssetType`, `params`)
- `simulate_fv` / `base_trade_prob` / etc. become **stubs** for R5 assets — those methods aren't called when the scenario is `R5Scenario`. The trait stays compatible so R3/R4 assets continue to work.

### Phase 4 — calibration
- Per-asset: fit `(σ_OU, θ_OU, μ_per_day, h, depth_L1, depth_L2)` from historical CSVs (3 days)
- Pulse rates: fit Poisson rate per group from observed pulse counts
- Constraints: hard-coded (Pebbles sum = 50000, Choc+Van K_day fitted)
- Validate by replaying hold-1 scenario and comparing PnL distribution

### Phase 5 — strategy
- Build the R5 trader in 4 buckets (A: Pebbles basket, B: Snackpack pair+triplet+MM, C: vanilla MM, D: specials)
- Test under R5Scenario MC

## Calibration data needs

We have:
- 3 days × 30K ticks of historical prices ✓
- 35,385 trade events with full direction/quantity ✓
- Hold-1 portal sub (1K-tick day-4 backtest) ✓ — sanity-check only

We need to add:
- One MM portal sub eventually to back-fit elastic taker rate (R3 lesson — see CLAUDE.md). For day-1 strategies the calibrated rates from historical alone should be close enough to ship.

## Decision point

Phases 1+2 take ~1.5 days of Rust work; Phase 3 is straightforward (~half a day); calibration (Phase 4) is another half day. So total ~2.5 days before we can run accurate R5 MC.

Alternative cheaper paths:
- **`prosperity3bt` CSV replay**: works today, gives relative PnL comparisons, doesn't generate paths so can't do MC distribution
- **Simple Python sim** (no Rust): could prototype the scenario in Python in a day, run slowly. Useful for validating the model before Rust work. But not a long-term solution.

I think the right call is: **start with a Python prototype of R5Scenario (Phase 1+2 in Python)** to validate the model and the constraint enforcement. If it produces realistic synthetic data (compared to the historical CSVs), then port to Rust for performance (Phase 3+).

If the user wants speed over modelling rigor, we can skip the sim rebuild entirely and ship a strategy on `prosperity3bt` CSV replay alone. But that doesn't give us the distributional view (mean / std / 5th percentile) that we used for R3 trader selection.

## Recommended next step

1. Build a Python prototype of `R5Scenario` (~half day): one script that generates 3 synthetic days respecting all R5 invariants. Compare its statistics (per-asset mid std, pebble sum std, pulse rates, trade direction balance) to the historical CSVs.
2. If it matches → port to Rust and integrate into `prosperity4mcbt`.
3. If it doesn't match → iterate the model. Cheap to fix in Python, expensive in Rust.

Worst case: 1 day to validate model, then go straight to Rust port if it works.

## Decision needed from user

- ✅ Build R5Scenario as proposed (Python prototype → Rust port)?
- Push back on any of the modeling assumptions (e.g. OU vs RW, pulse-only bot model)?
- Other priorities first?
