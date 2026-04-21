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
