# GeoHealth 2026 submission 3466 revision

The submitted numerical results have **not** been rerun. The Overleaf manuscript
has been revised using the supplied feedback and existing aggregates. Code fixes
change routing behavior; new outputs must not be represented as the old experiment.

## Implemented

- Carry the original-network distance ceiling into the constrained solver and
  through the API's auxiliary route filtering. A smaller raster-covered graph
  cannot enlarge that ceiling.
- Use length-shortest parallel edges in a shortest-route fallback.
- Preserve route source, cap termination, label counts, rejection type, and the
  proportion of route length using a shade surrogate.
- Preserve sampled mean positive UTCI exceedance through objective projection.
  The old no-op projection replaced it by positive exceedance of the edge mean;
  these are different when samples straddle the threshold.
- Compare methods only on the intersection of successful OD-budget records,
  matched within study/config/run/raster snapshot. Reject duplicate records.
  Paired heat contrasts use OD-cluster bootstrap intervals.
- Retain rejected-attempt runtime summaries and failure-reason tables.
- Provide actual coefficient sweeps (0, 0.5 and 2 times each default weight),
  thresholds 24/26/28/32 C, 5/10/20/40 m spacing, UTCI offsets, and explicitly
  labeled deterministic shade mixing. Selected routes are scored on a common
  reference field; failures stay in the raw output.
- Add an offset-aware revision configuration and a metric OD plotting command.
- Fail clearly on unhydrated Git LFS input pointers.

## Required data and real-data execution

Recover the **original** `od_pairs.csv`, `routes_summary.csv`, routes GeoJSON,
failure logs and environment/provenance from Hopper. Do not regenerate OD pairs
and describe them as the original sample. Verify data/LFS objects and preserve
the historical outputs before running corrected code.

From the repository root, with the real data restored:

```bash
# First analyze the existing raw results; this does not require new routing.
python experiments/aggregate_results.py --config configs/dc_snapshot_review3466.yaml --routes-summary /absolute/path/to/original/routes_summary.csv

# Rerun corrected routing on the same original serialized OD pairs.
python experiments/run_route_benchmark.py --config configs/dc_snapshot_review3466.yaml --od-pairs /absolute/path/to/original/od_pairs.csv --methods shortest_distance azimuth_heuristic shadow_only heat_dose proposed_full weighted_sum
python experiments/run_review_sensitivity.py --config configs/dc_snapshot_review3466.yaml --od-pairs /absolute/path/to/original/od_pairs.csv --subset-size 100
python experiments/aggregate_results.py --config configs/dc_snapshot_review3466.yaml
python experiments/plot_od_pairs_metric.py --od-pairs /absolute/path/to/original/od_pairs.csv --output results/dc_snapshot_review3466/figures/od_pairs_metric.pdf
```

Use a separate directory/configuration when aggregating old and new raw records;
the example commands show the required inputs, not a license to overwrite the
first aggregation with a later run. Capture the actual Python/package versions,
Git commit, input checksums, machine details, and wall-clock/cache conditions.

`weighted_sum` is the existing unconstrained Dijkstra comparison. Its detour
must be reported, not silently treated as a budget-feasible environmental method.
Common-set comparisons default to the original five methods. The first 100
serialized OD pairs define the prespecified sensitivity subset; 35 variants at
four budgets yield 14,000 attempted sensitivity records for a complete subset.

## Remaining scientific requirements

- Real common-sample and sensitivity results are pending Hopper access.
- Redraw the actual OD coordinates in metric CRS; the current historical image
  is clearly identified as an endpoint-coverage display, not distance evidence.
- Additional cities/hours and exact small-instance solver comparisons have not
  been run; the manuscript limits claims to one modeled DC snapshot.
- Publish a frozen data/OD/results release and confirm usable LFS objects.
- Insert ACM-supplied rights/DOI/ISBN only when actually provided. Review the
  compiled PDF and final page limit before any workshop or arXiv submission.

The revision package is a draft for scientific review, not a claim that these
remaining analyses have already been completed.
