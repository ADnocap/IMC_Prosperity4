//! Asset registry. To add a new asset:
//!   1. Create `assets/<snake_lowercase>.rs` implementing `AssetSim`.
//!   2. Register it in `REGISTRY` below (symbol ↔ `build` function).
//!   3. `cargo build --release`.
//!
//! The sim detects which assets a trader uses by scanning the trader file for
//! `NAME = "ASSET_SYMBOL"` lines (see `detect::detect_assets`). Only assets
//! present in both the registry and the trader are active for that run.

use crate::asset::{AssetSim, FlagSpec};
use anyhow::{Result, bail};
use std::collections::HashMap;

pub mod ash_coated_osmium;
pub mod intarian_pepper_root;
// R3 products (auto-generated from calibration/<asset>/params.json):
pub mod hydrogel_pack;
pub mod velvetfruit_extract;
pub mod vev_4000;
pub mod vev_4500;
pub mod vev_5000;
pub mod vev_5100;
pub mod vev_5200;
pub mod vev_5300;
pub mod vev_5400;
pub mod vev_5500;
pub mod vev_6000;
pub mod vev_6500;
// R5 products: one shared impl, 50 instances built from calibration/r5/scenario_params.json.
pub mod r5_asset;

/// One registry entry per known asset.
#[allow(dead_code)]
struct Entry {
    symbol: &'static str,
    // Kept on the struct so future `--help` / discovery tooling can enumerate flags
    // without building an asset. Not used in the current main loop.
    flag_specs: fn() -> Vec<FlagSpec>,
    build: fn(&HashMap<String, String>) -> Result<Box<dyn AssetSim>>,
}

const REGISTRY: &[Entry] = &[
    Entry {
        symbol: ash_coated_osmium::SYMBOL,
        flag_specs: ash_coated_osmium::flag_specs,
        build: ash_coated_osmium::build,
    },
    Entry {
        symbol: intarian_pepper_root::SYMBOL,
        flag_specs: intarian_pepper_root::flag_specs,
        build: intarian_pepper_root::build,
    },
    Entry {
        symbol: hydrogel_pack::SYMBOL,
        flag_specs: hydrogel_pack::flag_specs,
        build: hydrogel_pack::build,
    },
    Entry {
        symbol: velvetfruit_extract::SYMBOL,
        flag_specs: velvetfruit_extract::flag_specs,
        build: velvetfruit_extract::build,
    },
    Entry { symbol: vev_4000::SYMBOL, flag_specs: vev_4000::flag_specs, build: vev_4000::build },
    Entry { symbol: vev_4500::SYMBOL, flag_specs: vev_4500::flag_specs, build: vev_4500::build },
    Entry { symbol: vev_5000::SYMBOL, flag_specs: vev_5000::flag_specs, build: vev_5000::build },
    Entry { symbol: vev_5100::SYMBOL, flag_specs: vev_5100::flag_specs, build: vev_5100::build },
    Entry { symbol: vev_5200::SYMBOL, flag_specs: vev_5200::flag_specs, build: vev_5200::build },
    Entry { symbol: vev_5300::SYMBOL, flag_specs: vev_5300::flag_specs, build: vev_5300::build },
    Entry { symbol: vev_5400::SYMBOL, flag_specs: vev_5400::flag_specs, build: vev_5400::build },
    Entry { symbol: vev_5500::SYMBOL, flag_specs: vev_5500::flag_specs, build: vev_5500::build },
    Entry { symbol: vev_6000::SYMBOL, flag_specs: vev_6000::flag_specs, build: vev_6000::build },
    Entry { symbol: vev_6500::SYMBOL, flag_specs: vev_6500::flag_specs, build: vev_6500::build },
];

/// True if `symbol` is one of the 50 R5 products (best-effort: returns false
/// if the R5 calibration JSON can't be loaded; callers use this for routing,
/// not validation).
pub fn is_r5_symbol(symbol: &str) -> bool {
    crate::scenarios::r5::params()
        .map(|p| p.assets.contains_key(symbol))
        .unwrap_or(false)
}

pub fn is_known_symbol(symbol: &str) -> bool {
    REGISTRY.iter().any(|e| e.symbol == symbol) || is_r5_symbol(symbol)
}

#[allow(dead_code)]
pub fn flag_specs_for(symbol: &str) -> Result<Vec<FlagSpec>> {
    for entry in REGISTRY {
        if entry.symbol == symbol {
            return Ok((entry.flag_specs)());
        }
    }
    if is_r5_symbol(symbol) {
        return Ok(r5_asset::flag_specs());
    }
    bail!("unknown asset: {}", symbol);
}

pub fn build_asset(symbol: &str, flags: &HashMap<String, String>) -> Result<Box<dyn AssetSim>> {
    for entry in REGISTRY {
        if entry.symbol == symbol {
            return (entry.build)(flags);
        }
    }
    if is_r5_symbol(symbol) {
        return r5_asset::build_for_symbol(symbol, flags);
    }
    bail!("unknown asset: {}", symbol);
}

/// All known symbols (for diagnostics + help text). Includes R5 if calibration
/// can be loaded; falls back to just the static registry if it can't.
pub fn known_symbols() -> Vec<String> {
    let mut out: Vec<String> = REGISTRY.iter().map(|e| e.symbol.to_string()).collect();
    if let Ok(syms) = crate::scenarios::r5::symbols() {
        for s in syms {
            if !out.contains(&s) {
                out.push(s);
            }
        }
    }
    out
}
