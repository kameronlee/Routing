# Paper Assets

This directory contains small, commit-safe assets for the heat-routing pilot paper.

## Root Assets

The root-level CSV and PNG files are manuscript-ready convenience copies used by `paper/manuscript_draft.md`.

- `main_method_comparison.csv`
- `detour_tradeoff.csv`
- `success_by_method.png`
- `heat_reduction_vs_detour.png`
- `method_comparison.png`

## Frozen 500-Pair Main Snapshot

`500pair_main/` is the source-of-truth archive for the frozen 500-pair experiment used in the first manuscript draft.

- `500pair_main/tables/`: copied paper tables from `results/dc_snapshot_500pair_main_methods/tables/`
- `500pair_main/figures/`: copied small PNG figures from `results/dc_snapshot_500pair_main_methods/figures/`
- `500pair_main/reports/`: copied summary report for the frozen run

Full generated outputs remain ignored under `results/`, and source data remains under `data/`.
