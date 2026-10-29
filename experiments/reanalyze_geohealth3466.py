"""Reanalyze the archived GeoHealth pilot without rerunning the router."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from routing_backend.paired_comparison import (
    common_accepted_rows, index_records, paired_heat_contrasts, record_key, succeeded,
)
from routing_backend.result_metrics import summarize_by_group
from routing_backend.experiment_io import write_csv

METHODS = ["shortest_distance", "azimuth_heuristic", "shadow_only", "heat_dose", "proposed_full"]
NAMES = dict(zip(METHODS, ["Shortest", "Hybrid azimuth", "Direct shadow", "UTCI exceedance", "Composite"]))


def read_rows(directory, name):
    path = directory / name
    opener = open
    if not path.exists():
        path = path.with_suffix(path.suffix + ".gz")
        opener = gzip.open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return path, rows


def with_differences(rows, baselines):
    output = []
    for row in rows:
        value = dict(row)
        if succeeded(row):
            base = baselines[record_key(row)]
            for name, field, sign in [("delta_H_K", "heat_dose", 1), ("delta_U_K", "mean_utci", 1), ("delta_S", "shade_fraction", -1)]:
                value[name] = sign * (float(base[field]) - float(row[field]))
            value["extra_distance_percent"] = 100 * float(row["excess_distance_ratio"])
        output.append(value)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "paper_assets/review3466/raw")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "paper_assets/review3466/analysis")
    parser.add_argument("--figures", action="store_true")
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    paths_rows = [read_rows(args.raw_dir, name) for name in ["routes_summary.csv", "proposed_tuning_summary.csv", "od_pairs.csv"]]
    routes, tuning, od = [x[1] for x in paths_rows]
    assert len(routes) == 10000 and len(od) == 500 and len(tuning) == 800
    index_records(routes)
    index_records(tuning)
    assert {tuple(r[k] for k in ["study_name", "config_hash", "run_id", "raster_timestamp"]) for r in routes + tuning} == {("dc_snapshot", "5334dd51b5f7", "5334dd51b5f7", "2026-06-19T14:00:00")}
    assert {r["pair_id"] for r in tuning} == {r["pair_id"] for r in od[:100]}
    assert {r["detour_ratio"] for r in tuning} == {"0.1", "0.2"}
    for r in routes + tuning:
        if succeeded(r):
            ceiling = float(r["baseline_shortest_distance_m"]) * (1 + float(r["detour_ratio"]))
            assert float(r["route_distance_m"]) <= ceiling + 1e-6
    baselines = {record_key(r): r for r in routes if r["method"] == "shortest_distance" and succeeded(r)}
    enriched = with_differences(routes, baselines)
    common = common_accepted_rows(enriched, METHODS)
    metrics = ["delta_H_K", "delta_U_K", "delta_S", "extra_distance_percent", "runtime_ms", "scenic_score", "noise_score", "slope_penalty"]
    write_csv(out / "common_by_budget.csv", summarize_by_group(common, ["method", "detour_ratio"], metrics))
    pooled = summarize_by_group(common, ["method"], metrics)
    write_csv(out / "common_pooled.csv", pooled)
    contrasts = paired_heat_contrasts(enriched, METHODS)
    write_csv(out / "paired_heat_contrasts.csv", contrasts)
    write_csv(out / "all_attempt_runtime.csv", summarize_by_group(routes, ["method", "success"], ["runtime_ms"]))
    write_csv(out / "method_specific.csv", summarize_by_group([r for r in enriched if succeeded(r)], ["method"], metrics))

    variants = sorted({r["method"] for r in tuning})
    tune_index = index_records(tuning)
    tune_keys = sorted({record_key(r) for r in tuning})
    tune_common_keys = [key for key in tune_keys if all(succeeded(tune_index[(key, m)]) for m in variants)]
    tune_common = [tune_index[(key, m)] for key in tune_common_keys for m in variants]
    tune_enriched = with_differences(tune_common, baselines)
    write_csv(out / "tuning_common.csv", summarize_by_group(tune_enriched, ["method"], metrics + ["heat_dose"]))
    tune_base = variants[0]
    tune_contrasts = []
    for m in variants[1:]:
        clusters = defaultdict(list)
        for key in tune_common_keys:
            clusters[key[:-1]].append(float(tune_index[(key, tune_base)]["heat_dose"]) - float(tune_index[(key, m)]["heat_dose"]))
        # Same percentile bootstrap and OD clustering as the main comparison.
        from routing_backend.paired_comparison import _cluster_interval
        low, high = _cluster_interval(list(clusters.values()), 2000, 42)
        same_path = sum(tune_index[(key, tune_base)]["edge_ids"] == tune_index[(key, m)]["edge_ids"] for key in tune_common_keys)
        tune_contrasts.append({"method": m, "records": len(tune_common_keys), "od_pairs": len(clusters), "mean_extra_reduction_K": fmean(v for values in clusters.values() for v in values), "ci95_low_K": low, "ci95_high_K": high, "changed_routes": len(tune_common_keys) - same_path})
    write_csv(out / "tuning_paired.csv", tune_contrasts)
    sequences = defaultdict(set)
    for r in routes:
        if r["method"] == "shortest_distance":
            sequences[r["pair_id"]].add(r["edge_ids"])
    assert len(sequences) == 500 and all(len(v) == 1 for v in sequences.values())
    common_counts = Counter(r["detour_ratio"] for r in common if r["method"] == "shortest_distance")
    audit = {
        "analysis_type": "reanalysis of historical records; no corrected routing rerun",
        "source_sha256": {p.name.removesuffix('.gz'): hashlib.sha256(gzip.decompress(p.read_bytes()) if p.suffix == '.gz' else p.read_bytes()).hexdigest() for p, _ in paths_rows},
        "records": len(routes), "accepted": sum(succeeded(r) for r in routes),
        "common_records_per_method": len(common) // len(METHODS),
        "common_od_pairs": len({r['pair_id'] for r in common}), "common_by_budget": dict(common_counts),
        "failure_reasons": dict(Counter(r["failure_reason"] for r in routes if not succeeded(r))),
        "baseline_sequences_identical_across_budgets": True,
        "tuning_common_records_per_variant": len(tune_common_keys),
        "tuning_common_od_pairs": len({k[-2] for k in tune_common_keys}),
        "tuning_success_counts": dict(Counter(r['method'] for r in tuning if succeeded(r))),
        "bootstrap_replicates": 2000, "bootstrap_seed": 42,
    }
    (out / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))
    print("Pooled means:", [(r['method'], r['delta_H_K_mean'], r['extra_distance_percent_mean']) for r in pooled])
    print("Tuning contrasts:", tune_contrasts)
    if args.figures:
        make_figures(routes, od, out)


def make_figures(routes, od, out):
    from make_geohealth_figures import build_figures
    build_figures(routes, od, out)


if __name__ == "__main__":
    main()
