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

pub fn is_known_symbol(symbol: &str) -> bool {
    REGISTRY.iter().any(|e| e.symbol == symbol)
}

#[allow(dead_code)]
pub fn flag_specs_for(symbol: &str) -> Result<Vec<FlagSpec>> {
    for entry in REGISTRY {
        if entry.symbol == symbol {
            return Ok((entry.flag_specs)());
        }
    }
    bail!("unknown asset: {}", symbol);
}

pub fn build_asset(symbol: &str, flags: &HashMap<String, String>) -> Result<Box<dyn AssetSim>> {
    for entry in REGISTRY {
        if entry.symbol == symbol {
            return (entry.build)(flags);
        }
    }
    bail!("unknown asset: {}", symbol);
}

/// All known symbols (for diagnostics + help text).
pub fn known_symbols() -> Vec<&'static str> {
    REGISTRY.iter().map(|e| e.symbol).collect()
}
