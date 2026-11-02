# GeoHealth 3466 revision

The revised 5 m experiment uses the original 500 OD pairs and recovered Git LFS
inputs. The complete 20 m reference is rescored on the same 5 m field. All 10,000 corrected attempts succeed within the original-network
budgets. Every method is compared on the same 2,000 pair–budget cases.
Original shortest distances and common-field baseline scores agree exactly.

## Reviewer comments

| Comment | Change |
| --- | --- |
| R1: reproducibility | Public code, versioned inputs, exact OD pairs, raw route records, checksums, executed source, and rerun commands. |
| R1: presentation | Two vector figures show sample geography and recorded route changes. Fallback counts are in the main table; runtime is summarized in text. Labels are at least 8 pt at print width. |
| R1/R3: contribution | The paper compares objective settings within one solver and credits constrained-path methods and related heat/shade routing work. |
| R2: scope | Claims remain limited to one modeled DC hour. No cross-city or time-transfer claim. |
| R3: unequal subsets | All 500 pairs at all four allowances; intervals resample whole OD pairs. |
| R3: weights | Sixteen one-factor/reference settings on the same 100 pairs: 1,600 successful attempts, all rescored on a common field. |
| R3: threshold/spacing | Thresholds 24/28°C and sampling intervals 5/10/20/40 m are tested. The full-cohort rerun changes 70–76% of environmental paths; both grids are scored at 5 m and convergence is not claimed. |
| R4: metric/failures | Mean exceedance and exceedance–distance are distinguished. Fallback is explicit; acceptance does not imply a cooler or optimal route. |
| R4: context/runtime | Historical walking commute context, projected maps, original network distances, and runtime quantiles covering every attempt. |

## Corrections and checks

The rerun fixes the original-network ceiling, shortest parallel-edge fallback,
and sampled exceedance. The hybrid proxy now uses building height above
ground (`max(0, DSM - DEM)`), not absolute surface elevation. 73 tests pass;
two optional Torch tests are skipped.

Exact enumeration agrees on 2,400 small reference cases. A separate set of
200 deliberately difficult chain cases exposes the default cap: 150 searches
truncate, with a 42.3% mean relative cost gap. These are generated search
checks, not estimates of the DC optimality gap.

## Remaining limits

The study covers one modeled DC hour, with uncalibrated weights, no independent
environmental measurements, and unknown city-scale search gaps. The modeled
results do not establish pedestrian comfort, safety, or health benefit.

[Experiment commands](../experiments/README.md) reproduce the artifacts.
Historical records remain separate from the corrected result tables.
