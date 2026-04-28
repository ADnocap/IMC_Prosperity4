//! Scans a trader submission for asset declarations.
//!
//! Convention: at the top of the trader file (before the Trader class) declare
//! your assets as `NAME = "ASSET_SYMBOL"` — e.g. `OSMIUM = "ASH_COATED_OSMIUM"`.
//! For R5+, traders may also declare a tuple of symbols
//! (`GALAXY_SOUNDS = ("GALAXY_SOUNDS_DARK_MATTER", ...)`) — the scanner picks up
//! any quoted string that matches a known symbol within the prefix it scans.
//! This scanner reads the first 160 lines, extracts every string literal that
//! matches `^[A-Z_][A-Z0-9_]*$`, filters to known symbols in the asset registry,
//! and returns them in deterministic order.

use crate::assets;
use anyhow::{Context, Result, bail};
use std::collections::BTreeSet;
use std::fs;
use std::path::Path;

const SCAN_LINES: usize = 160;

pub fn detect_assets(trader_path: &Path) -> Result<Vec<String>> {
    let text = fs::read_to_string(trader_path)
        .with_context(|| format!("reading trader file {}", trader_path.display()))?;

    let mut found = BTreeSet::new();
    for line in text.lines().take(SCAN_LINES) {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        // Original form: `NAME = "ASSET_SYMBOL"`.
        if let Some(symbol) = extract_string_assignment(line) {
            if is_symbol_like(&symbol) && assets::is_known_symbol(&symbol) {
                found.insert(symbol);
            }
        }
        // Fallback: pull any bare double/single-quoted string literals on the
        // line — covers tuple/list literals like `("GALAXY_SOUNDS_DARK_MATTER",`.
        for symbol in extract_quoted_strings(line) {
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

/// Extract every quoted string literal on the line. Stops at the first `#`
/// (line comment). Handles plain `"..."` or `'...'` — no escape support, which
/// is fine for symbol declarations.
fn extract_quoted_strings(line: &str) -> Vec<String> {
    // Strip line comment.
    let line = match line.find('#') {
        Some(i) => &line[..i],
        None => line,
    };
    let mut out = Vec::new();
    let bytes = line.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i];
        if c == b'"' || c == b'\'' {
            let quote = c;
            let start = i + 1;
            let mut j = start;
            while j < bytes.len() && bytes[j] != quote {
                j += 1;
            }
            if j > start && j < bytes.len() {
                if let Ok(s) = std::str::from_utf8(&bytes[start..j]) {
                    out.push(s.to_string());
                }
                i = j + 1;
                continue;
            } else {
                break;
            }
        }
        i += 1;
    }
    out
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
