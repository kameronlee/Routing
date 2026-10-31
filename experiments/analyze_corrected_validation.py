#!/usr/bin/env python
"""Audit and summarize corrected route records and fixed-cohort sensitivity runs."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path
from statistics import fmean, median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from routing_backend.experiment_io import write_csv
from routing_backend.paired_comparison import (
    common_accepted_rows, index_records, paired_heat_contrasts, record_key, succeeded,
)

METHODS = ["shortest_distance", "azimuth_heuristic", "shadow_only", "heat_dose", "proposed_full"]


def read_csv(path):
    with (gzip.open(path, "rt", newline="") if path.suffix == ".gz" else path.open(newline="")) as stream:
        return list(csv.DictReader(stream))


def summarize(rows):
    baselines = {record_key(row): row for row in rows
                 if row["method"] == "shortest_distance" and succeeded(row)}
    enriched = []
    for row in rows:
        item = dict(row)
        if succeeded(row):
            baseline = baselines[record_key(row)]
            length = float(row["route_distance_m"])
            item["delta_H_K"] = float(baseline["heat_dose"]) - float(row["heat_dose"])
            item["delta_U_K"] = float(baseline["mean_utci"]) - float(row["mean_utci"])
            item["delta_peak_K"] = float(baseline["max_utci"]) - float(row["max_utci"])
            item["delta_S"] = float(row["shade_fraction"]) - float(baseline["shade_fraction"])
            item["J_K_m"] = length * float(row["heat_dose"])
            item["delta_J_K_m"] = float(baseline["route_distance_m"]) * float(baseline["heat_dose"]) - item["J_K_m"]
            item["extra_percent"] = 100 * float(row["excess_distance_ratio"])
        enriched.append(item)
    return enriched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "paper_assets/review3466/corrected/raw")
    parser.add_argument("--output", type=Path, default=ROOT / "paper_assets/review3466/corrected/analysis")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    provenance = json.loads((args.raw / "provenance.json").read_text())
    for name, expected in provenance["files_sha256"].items():
        path = args.raw / name
        assert path.parent == args.raw, "Unexpected nested raw-data path"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, f"Checksum mismatch: {name}"
    main_path = args.raw / "routes_summary.csv.gz"
    rows = read_csv(main_path)
    indexed = index_records(rows)
    assert len(rows) == len(indexed) == 10_000
    assert Counter(row["method"] for row in rows) == Counter({method: 2000 for method in METHODS})
    assert len({row["pair_id"] for row in rows}) == 500
    baseline_sequences = defaultdict(set)
    for row in rows:
        if succeeded(row):
            ceiling = float(row["baseline_shortest_distance_m"]) * (1 + float(row["detour_ratio"]))
            assert float(row["route_distance_m"]) <= ceiling + 1e-6
            assert abs(float(row["maximum_distance_m"]) - ceiling) < 1e-6
            if row["method"] == "shortest_distance":
                baseline_sequences[row["pair_id"]].add(row["edge_ids"])
    assert len(baseline_sequences) == 500 and all(len(paths) == 1 for paths in baseline_sequences.values())
    enriched = summarize(rows)
    common = common_accepted_rows(enriched, METHODS)
    common_baselines = {record_key(row): row for row in common if row["method"] == "shortest_distance"}
    summary = []
    for budget in ["all", "0.05", "0.1", "0.2", "0.3"]:
        for method in METHODS:
            selected = [row for row in common if row["method"] == method and
                        (budget == "all" or float(row["detour_ratio"]) == float(budget))]
            if not selected:
                continue
            values = {key: [float(row[key]) for row in selected] for key in
                      ("delta_H_K", "delta_U_K", "delta_peak_K", "delta_S", "delta_J_K_m", "extra_percent")}
            summary.append({"method": method, "budget": budget, "common_cases": len(selected),
                **{f"mean_{key}": fmean(value) for key, value in values.items()},
                "median_delta_H_K": median(values["delta_H_K"]),
                "median_delta_peak_K": median(values["delta_peak_K"]),
                "lower_H_higher_J": sum(float(r["delta_H_K"]) > 1e-9 and float(r["delta_J_K_m"]) < -1e-6 for r in selected),
                "higher_H": sum(value < -1e-9 for value in values["delta_H_K"]),
                "lower_J": sum(value > 1e-6 for value in values["delta_J_K_m"]),
                "unchanged_edges": sum(r["edge_ids"] == common_baselines[record_key(r)]["edge_ids"] for r in selected),
            })
    write_csv(args.output / "matched_outcomes.csv", summary, list(summary[0]))
    contrasts = paired_heat_contrasts(enriched, METHODS)
    write_csv(args.output / "paired_heat_contrasts.csv", contrasts, list(contrasts[0]))
    sources, runtimes = [], []
    for method in METHODS:
        selected = [row for row in rows if row["method"] == method]
        counts = Counter((row["success"], row["route_source"], row["search_stop_reason"]) for row in selected)
        sources.extend({"method": method, "success": success, "route_source": source,
                        "stop_reason": reason, "count": count}
                       for (success, source, reason), count in sorted(counts.items()))
        times = np.array([float(row["runtime_ms"]) / 1000 for row in selected])
        runtimes.append({"method": method, "n": len(times), "min_s": min(times),
                         "median_s": float(np.median(times)), "p90_s": float(np.quantile(times, .9)),
                         "p99_s": float(np.quantile(times, .99)), "max_s": max(times)})
    write_csv(args.output / "route_sources.csv", sources, list(sources[0]))
    write_csv(args.output / "runtime_summary.csv", runtimes, list(runtimes[0]))
    old = read_csv(ROOT / "paper_assets/review3466/raw/routes_summary.csv.gz")
    old_index = {(r["pair_id"], float(r["detour_ratio"]), r["method"]): r for r in old}
    baseline_errors = [float(row["heat_dose"]) - float(old_index[(row["pair_id"], float(row["detour_ratio"]), row["method"])]["heat_dose"])
                       for row in rows if row["method"] == "shortest_distance" and succeeded(row)]
    audit = {"attempts": len(rows), "successes": sum(succeeded(row) for row in rows),
             "common_pair_budget_cases": len(common) // len(METHODS),
             "common_od_pairs": len({r["pair_id"] for r in common}),
             "baseline_max_abs_H_error_K_vs_archive": max(map(abs, baseline_errors)),
             "raw_main_sha256": hashlib.sha256(main_path.read_bytes()).hexdigest(),
             "note": "Shards retain their original configuration/run identifiers; matching stays within each shard."}
    sens_path = args.raw / "review_sensitivity_summary.csv.gz"
    if sens_path.exists():
        sensitivity = read_csv(sens_path)
        dense = read_csv(args.raw / "dense_path_check.csv.gz")
        assert len(sensitivity) == len(dense) == 1600
        dense_index = {(r["pair_id"], r["method"]): r for r in dense}
        assert len(dense_index) == len(dense)
        reference = {r["pair_id"]: r for r in dense if r["method"] == "reference"}
        by_pair = defaultdict(list)
        for row in sensitivity:
            by_pair[row["pair_id"]].append(row)
        common_pairs = {pair for pair, group in by_pair.items() if len(group) == 16 and
                        all(succeeded(r) and dense_index[(pair, r["method"])]["dense_success"].lower() == "true"
                            for r in group)}
        variants = []
        for method in dict.fromkeys(r["method"] for r in sensitivity):
            selected = [r for r in sensitivity if r["method"] == method]
            valid = [r for r in selected if r["pair_id"] in common_pairs]
            dense_differences = [float(reference[r["pair_id"]]["H_5m_K"]) - float(dense_index[(r["pair_id"], method)]["H_5m_K"]) for r in valid]
            spacing_errors = ([float(dense_index[(r["pair_id"], method)]["H_selection_spacing_K"]) - float(dense_index[(r["pair_id"], method)]["H_5m_K"]) for r in valid]
                              if method == "reference" or method.startswith("sampling_") else [])
            variants.append({"method": method, "attempts": len(selected),
                             "successes": sum(succeeded(r) for r in selected), "dense_common_cases": len(valid),
                             "path_changes": sum(r["route_changed"].lower() == "true" for r in valid),
                             "mean_reference_H_minus_variant_H_5m_K": fmean(dense_differences) if valid else None,
                             "mean_extra_percent": fmean(100 * float(r["excess_distance_ratio"]) for r in valid) if valid else None,
                             "median_abs_spacing_error_K": median(map(abs, spacing_errors)) if spacing_errors else None,
                             "p90_abs_spacing_error_K": float(np.quantile(np.abs(spacing_errors), .9)) if spacing_errors else None,
                             "max_abs_spacing_error_K": max(map(abs, spacing_errors)) if spacing_errors else None})
        write_csv(args.output / "sensitivity_outcomes.csv", variants, list(variants[0]))
        audit["sensitivity_attempts"] = len(sensitivity)
        audit["sensitivity_successes"] = sum(succeeded(r) for r in sensitivity)
        audit["dense_check_successes"] = sum(r["dense_success"].lower() == "true" for r in dense)
        audit["sensitivity_common_pairs"] = len(common_pairs)
        audit["reference_control_path_changes"] = sum(r["method"] == "reference" and r["route_changed"].lower() == "true" for r in sensitivity)
    (args.output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
