# DC pilot results

The historical run has 500 OD pairs, four budgets, and five methods: 10,000
attempts, of which 8,093 succeed. All 1,907 failures log the expansion limit.

On the same 1,386 successful OD–budget records for every method:

| Method | Mean exceedance reduction (K) | Mean extra distance |
|---|---:|---:|
| Hybrid azimuth | 0.639 | 8.70% |
| Direct shadow | 0.693 | 9.30% |
| UTCI exceedance | 0.701 | 9.27% |
| Composite | 0.576 | 8.32% |

These conditional means cover 459 OD pairs. They are not an estimate for every
attempted trip. The paired exceedance–composite difference is 0.125 K
(OD-cluster 95% interval: 0.108–0.142 K).

The archived joint-weight run has 142 common successful records. Its three
alternatives improve mean exceedance by another 0.044–0.050 K and change
25–30% of paths. This is limited tuning evidence, not a full sensitivity study.

[Raw records](../paper_assets/review3466/raw/) and
[analysis tables](../paper_assets/review3466/analysis/) accompany the paper.
Run `python experiments/reanalyze_geohealth3466.py --figures` to recompute them.
