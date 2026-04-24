"""Calibration pipeline — Python port of the visualizer's 9-stage Calibration tab.

Mirrors `visualizer/src/pages/calibration/stages/*.ts` and the WASM kernels in
`wasm_compute/src/{calibration,formula_search}.rs`. Same approximations are used
(Abramowitz-Stegun erf, Wilson-Hilferty chi2, Acklam inv_normal) so p-values
match the visualizer to ~7 sig-figs.

Entry point: `calibration/run_pipeline.py <ASSET>` (or `python -m calibration.pipeline.cli`).
"""
