# GeoHealth 3466 revision

The revised paper is in [geohealth3466/](geohealth3466/). It uses the original
10,000 route records recovered from Hopper on October 28, 2026.

## Reviewer checks

| Comment | Revision and remaining limit |
| --- | --- |
| R1: code and data | Code, OD pairs, original route records, checksums, and figure inputs are shared. Reanalysis is reproducible; complete historical graph/raster recovery is still missing. |
| R1: presentation | All figures and tables are referenced. Figure labels are at least 8 pt at print width. Captions are shorter; Figure 2 links one recorded route comparison to all 309 matched pairs at a 20% allowance. |
| R1/R3: contribution | The introduction identifies a computational benchmark, with established constrained-routing methods. Related work includes Skoumas et al. and CoolPaths. |
| R2: broader evaluation | Claims are restricted to one modeled DC hour. No new city or time-period experiment has been completed. |
| R3: unequal subsets | Table 5 uses the same 1,386 successful pair–budget records from 459 OD pairs for every method. Intervals resample whole OD pairs. |
| R3: weights | Historical joint-weight tuning is reanalyzed on 142 common records from 81 pairs. Independent coefficient, threshold, and spacing sweeps remain unrun. |
| R3: threshold, spacing, sidewalks | The 26°C reference is cited. The 20 m spacing is a computational choice without a convergence result. Centerline/sidewalk shade differences are explicit limitations. |
| R4: metric and failures | The composite is identified as an uncalibrated engineering score. All 1,907 failures log the expansion limit; the paper does not equate them with geographic infeasibility. |
| R4: walking, distances, runtime | The paper cites historical DC walking commute data, uses projected maps and original network distances, and plots complete accepted/rejected runtime distributions. |

## Reproduce the reanalysis

```bash
python experiments/reanalyze_geohealth3466.py --figures
```

Inputs and checksums are under `paper_assets/review3466/raw/`; outputs are under
`paper_assets/review3466/analysis/`. The script checks matching identifiers,
duplicate records, distance ceilings, the OD subset, and baseline sequences.
Figure inputs and source attribution are in
`paper_assets/review3466/figure_inputs/`. Maps use frozen DC GIS background
layers for context, separate from the historical routing inputs.

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
