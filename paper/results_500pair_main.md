# 500-Pair Main Experiment Result

This file records the frozen result used for the first manuscript draft.

## Configuration

- Config: `configs/dc_snapshot_500pair_main_methods.yaml`
- OD pairs: 500
- Route attempts: 2000 for `proposed_full` across detour settings
- Study area: Washington, DC raster/graph coverage
- Evidence type: modeled UTCI/direct-shadow computational benchmark
- Field validation: not performed

## Main finding

The 500-pair experiment shows that heat-aware routing reduces modeled heat exposure relative to shortest-distance routing under explicit detour budgets.

## Key result: proposed_full

- Successes: 1554 / 2000
- Failures: 446
- Mean heat-dose reduction: 0.597
- Mean UTCI reduction: 0.604 C
- Mean excess distance: 8.93%

## Comparison to thermal baselines

- `heat_dose`: mean heat-dose reduction 0.710, mean UTCI reduction 0.717 C, mean excess distance 9.57%
- `shadow_only`: mean heat-dose reduction 0.706, mean UTCI reduction 0.713 C, mean excess distance 9.66%
- `azimuth_heuristic`: mean heat-dose reduction 0.656, mean UTCI reduction 0.663 C, mean excess distance 9.16%

## Interpretation

`proposed_full` is not the strongest pure thermal optimizer. Simpler thermal baselines such as `heat_dose` and `shadow_only` achieved larger heat-dose reductions. However, `proposed_full` had the strongest success count among constrained thermal methods and the lowest excess distance, making it the most feasible and distance-efficient combined method in this experiment.

## Correct claim

The backend demonstrates the feasibility of constrained heat-aware pedestrian routing using modeled UTCI and direct-shadow rasters.

## Incorrect claim

The results do not prove that `proposed_full` is the best thermal method, nor do they prove real-world human comfort improvements without field validation.
