# GeoHealth 3466 revision

The revised paper is in [geohealth3466/](geohealth3466/). It uses the original
10,000 route records recovered from Hopper on October 28, 2026.

The revision adds:

- A common-set comparison: 1,386 OD–budget records from 459 OD pairs.
- OD-cluster bootstrap intervals, keeping repeated budgets together.
- Joint-weight tuning on 142 common records from 81 pairs.
- The original OD map in metric coordinates and runtimes for failed attempts.
- A clear account of the expansion-limit failures and implementation audit.

The README and paper now distinguish the historical experiment from the code
fixes. The archived failures all log the 20,000-expansion limit. They do not
show that those neighborhoods have no feasible or cooler walking route.

## Reproduce the reanalysis

```bash
python experiments/reanalyze_geohealth3466.py --figures
```

Inputs and checksums are under `paper_assets/review3466/raw/`; outputs are under
`paper_assets/review3466/analysis/`. The script checks matching identifiers,
duplicate records, distance ceilings, the OD subset, and baseline sequences.

## Still needed

The exact historical code/environment and complete frozen raster/graph inputs
are not pinned. A corrected real-data rerun, independent coefficient sweeps,
threshold checks, sampling convergence, and additional cities/hours remain
unfinished. The September uncertainty runs use a different design and are not
evidence for this pilot.

With verified real inputs, run the revision config against the original OD CSV:

```bash
python experiments/run_route_benchmark.py --config configs/dc_snapshot_review3466.yaml --od-pairs paper_assets/review3466/raw/od_pairs.csv --methods shortest_distance azimuth_heuristic shadow_only heat_dose proposed_full weighted_sum
python experiments/run_review_sensitivity.py --config configs/dc_snapshot_review3466.yaml --od-pairs paper_assets/review3466/raw/od_pairs.csv --subset-size 100
python experiments/aggregate_results.py --config configs/dc_snapshot_review3466.yaml
```

The 35-variant sensitivity run attempts 14,000 records. It has not been run for
this revision. The limited historical tuning changes several weights together
and does not establish robustness to the threshold or sample spacing.
