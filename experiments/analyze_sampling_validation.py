#!/usr/bin/env python
"""Compare 20 m and 5 m route selection on the same 5 m reporting field."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from statistics import fmean
import subprocess
import sys
import tarfile

import numpy as np

from analyze_corrected_validation import ROOT, METHODS, read_csv
from routing_backend.experiment_io import write_csv
from routing_backend.paired_comparison import _cluster_interval, succeeded


def key(row):
    return row["pair_id"], float(row["detour_ratio"]), row["method"]


def verified_source(asset, expected):
    result = {}
    with tarfile.open(asset / "executed_source.tar.gz") as archive:
        for name, checksum in expected.items():
            matches = [m for m in archive.getmembers() if m.name == name or m.name.endswith("/" + name)]
            assert len(matches) == 1, name
            content = archive.extractfile(matches[0]).read()
            assert hashlib.sha256(content).hexdigest() == checksum, name
            result[name] = content.replace(b"\r\n", b"\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=ROOT / "paper_assets/review3466/sampling5")
    args = parser.parse_args()
    raw, analysis = args.assets / "raw", args.assets / "analysis"
    old_raw = ROOT / "paper_assets/review3466/corrected/raw"
    subprocess.run([sys.executable, str(ROOT / "experiments/analyze_corrected_validation.py"),
                    "--raw", str(raw), "--output", str(analysis)], check=True)
    inputs = json.loads((raw / "inputs.json").read_text())["inputs"]
    old_inputs = json.loads((old_raw / "inputs.json").read_text())["inputs"]
    assert set(inputs) == set(old_inputs)
    assert all(v["sha256"] == old_inputs[name]["sha256"] for name, v in inputs.items())
    new_source = json.loads((raw / "provenance.json").read_text())["source_sha256"]
    old_source = json.loads((old_raw / "provenance.json").read_text())["source_sha256"]
    # The original sensitivity module was uploaded with CRLF line endings.
    # Preserve and verify both byte hashes, then compare the actual code text.
    assert verified_source(args.assets, new_source) == verified_source(old_raw.parent, old_source), \
        "Routing implementation changed between sampling runs"
    line_ending_only = [name for name in new_source if new_source[name] != old_source[name]]
    native = {key(r): r for r in read_csv(raw / "routes_summary.csv.gz")}
    old = {key(r): r for r in read_csv(old_raw / "routes_summary.csv.gz")}
    report = {key(r): r for r in read_csv(raw / "reference_rescored.csv.gz")}
    assert len(native) == len(old) == len(report) == 10000
    assert native.keys() == old.keys() == report.keys()
    cases = sorted({k[:2] for k in native})
    common = [c for c in cases if all(succeeded(native[c + (m,)]) and
              succeeded(old[c + (m,)]) and report[c + (m,)]["rescore_success"].lower() == "true"
              for m in METHODS)]
    baseline_errors = []
    for c in common:
        k = c + ("shortest_distance",)
        assert json.loads(native[k]["edge_ids"]) == json.loads(old[k]["edge_ids"])
        baseline_errors.append(abs(float(native[k]["heat_dose"]) - float(report[k]["H_reporting_K"])))
    assert max(baseline_errors) < 1e-9
    paired, summaries = [], []
    for method in METHODS:
        selected = []
        for c in common:
            k, b = c + (method,), c + ("shortest_distance",)
            baseline = float(native[b]["heat_dose"])
            old_h, new_h = float(report[k]["H_reporting_K"]), float(native[k]["heat_dose"])
            item = {"pair_id": c[0], "detour_ratio": c[1], "method": method,
                    "path_changed": json.loads(native[k]["edge_ids"]) != json.loads(old[k]["edge_ids"]),
                    "delta_H_20m_routes_at_5m_K": baseline - old_h,
                    "delta_H_5m_routes_K": baseline - new_h,
                    "H_20m_route_minus_5m_route_K": old_h - new_h,
                    "H_20m_report_minus_5m_report_same_path_K": float(old[k]["heat_dose"]) - old_h}
            paired.append(item)
            selected.append(item)
        clusters = defaultdict(list)
        for r in selected:
            clusters[r["pair_id"]].append(r["H_20m_route_minus_5m_route_K"])
        low, high = _cluster_interval(list(clusters.values()), 2000, 42)
        summaries.append({"method": method, "attempts_per_spacing": 2000,
            "native_successes": sum(succeeded(r) for k, r in native.items() if k[2] == method),
            "reference_rescore_successes": sum(r["rescore_success"].lower() == "true" for k, r in report.items() if k[2] == method),
            "common_cases": len(selected), "common_od_pairs": len(clusters),
            "changed_paths": sum(r["path_changed"] for r in selected),
            "changed_percent": 100 * fmean(r["path_changed"] for r in selected),
            "mean_delta_H_20m_routes_at_5m_K": fmean(r["delta_H_20m_routes_at_5m_K"] for r in selected),
            "mean_delta_H_5m_routes_K": fmean(r["delta_H_5m_routes_K"] for r in selected),
            "mean_H_20m_route_minus_5m_route_K": fmean(r["H_20m_route_minus_5m_route_K"] for r in selected),
            "ci95_low_K": low, "ci95_high_K": high,
            "median_abs_20m_reporting_error_K": float(np.median([
                abs(r["H_20m_report_minus_5m_report_same_path_K"]) for r in selected]))})
    write_csv(analysis / "sampling_paired.csv", paired, list(paired[0]))
    write_csv(analysis / "sampling_comparison.csv", summaries, list(summaries[0]))
    audit_path = analysis / "audit.json"
    audit = json.loads(audit_path.read_text())
    audit["baseline_native_H_change_vs_historical_20m_K"] = audit.pop("baseline_max_abs_H_error_K_vs_archive")
    audit.update(shared_input_checksums_match=True, shared_routing_code_matches_after_LF_normalization=True,
                 source_files_with_line_ending_only_differences=line_ending_only,
                 paired_grid_cases=len(common), paired_grid_od_pairs=len({c[0] for c in common}),
                 baseline_common_field_max_error_K=max(baseline_errors),
                 reference_paths_rescored=sum(r["rescore_success"].lower() == "true" for r in report.values()),
                 note="Primary 5 m run; frozen 20 m paths are compared on the same 5 m field.")
    audit_path.write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
