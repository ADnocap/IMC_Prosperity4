//! Scans a trader submission for asset declarations.
//!
//! Convention: at the top of the trader file (before the Trader class) declare
//! your assets as `NAME = "ASSET_SYMBOL"` — e.g. `OSMIUM = "ASH_COATED_OSMIUM"`.
//! This scanner reads the first 40 lines, extracts every string literal that
//! matches `^[A-Z_][A-Z0-9_]*$`, filters to known symbols in the asset registry,
//! and returns them in deterministic order.

use crate::assets;
use anyhow::{Context, Result, bail};
use std::collections::BTreeSet;
use std::fs;
use std::path::Path;

const SCAN_LINES: usize = 40;

pub fn detect_assets(trader_path: &Path) -> Result<Vec<String>> {
    let text = fs::read_to_string(trader_path)
        .with_context(|| format!("reading trader file {}", trader_path.display()))?;

    let mut found = BTreeSet::new();
    for line in text.lines().take(SCAN_LINES) {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        // Match `NAME = "SOMETHING"` (single or double quotes).
        if let Some(symbol) = extract_string_assignment(line) {
            if is_symbol_like(&symbol) && assets::is_known_symbol(&symbol) {
                found.insert(symbol);
            }
        }
    }

    if found.is_empty() {
        bail!(
            "no known asset symbols detected in the first {} lines of {}. \
             Expected lines like `OSMIUM = \"ASH_COATED_OSMIUM\"` matching one of {:?}.",
            SCAN_LINES,
            trader_path.display(),
            assets::known_symbols()
        );
    }
    Ok(found.into_iter().collect())
}

fn extract_string_assignment(line: &str) -> Option<String> {
    let (_, rhs) = line.split_once('=')?;
    let rhs = rhs.trim().trim_end_matches(';');
    // Strip inline comments.
    let rhs = match rhs.find('#') {
        Some(idx) => rhs[..idx].trim(),
        None => rhs,
    };
    if (rhs.starts_with('"') && rhs.ends_with('"'))
        || (rhs.starts_with('\'') && rhs.ends_with('\''))
    {
        if rhs.len() < 2 {
            return None;
        }
        Some(rhs[1..rhs.len() - 1].to_string())
    } else {
        None
    }
}

fn is_symbol_like(s: &str) -> bool {
    if s.is_empty() {
        return false;
    }
    s.chars()
        .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_')
        && s.chars().next().map_or(false, |c| c.is_ascii_uppercase() || c == '_')
}
