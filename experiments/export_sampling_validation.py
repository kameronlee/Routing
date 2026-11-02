#!/usr/bin/env python
"""Freeze the full 5 m rerun, common-field rescoring, and sensitivity records."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import numpy as np

from export_validation_bundle import ROOT, METHODS, copy_metadata, digest, freeze_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "results/sampling-validation")
    parser.add_argument("--shards", type=int, default=32)
    parser.add_argument("--sensitivity-shards", type=int, default=8)
    parser.add_argument("--jobs", default="")
    args = parser.parse_args()
    asset = ROOT / "paper_assets/review3466/sampling5"
    raw = asset / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    manifests = []
    for i in range(args.shards):
        path = args.results / f"routes-{i}"
        manifest = json.loads((path / "manifest.json").read_text())
        assert manifest["finished_utc"] and manifest["config"]["sample_spacing_m"] == 5
        for name, checksum in manifest["outputs"].items():
            assert digest(path / name) == checksum
        manifests.append(manifest)
        copy_metadata(path / "manifest.json", raw / f"main_shard_{i}.json")
        rescore = args.results / f"rescore-{i}"
        checks = json.loads((rescore / "rescore_manifest.json").read_text())
        assert checks["finished_utc"]
        assert digest(rescore / "reference_rescored.csv") == checks["output_sha256"]
        copy_metadata(rescore / "rescore_manifest.json", raw / f"rescore_shard_{i}.json")
    assert all(m["source_sha256"] == manifests[0]["source_sha256"] for m in manifests)
    assert all(m["runner_sha256"] == manifests[0]["runner_sha256"] for m in manifests)
    rows = freeze_csv([args.results / f"routes-{i}/routes_summary.csv" for i in range(args.shards)],
                      raw / "routes_summary.csv.gz", 10000)
    rescored = freeze_csv([args.results / f"rescore-{i}/reference_rescored.csv" for i in range(args.shards)],
                         raw / "reference_rescored.csv.gz", 10000)
    settings = [args.results / f"sensitivity-{i}" for i in range(args.sensitivity_shards)]
    freeze_csv([p / "review_sensitivity_summary.csv" for p in settings],
               raw / "review_sensitivity_summary.csv.gz", 1600)
    freeze_csv([p / "dense_path_check.csv" for p in settings], raw / "dense_path_check.csv.gz", 1600)
    for i, path in enumerate(settings):
        for name, label in (("validation_protocol.json", "sensitivity"),
                            ("review_sensitivity_protocol.json", "sensitivity_reporting")):
            copy_metadata(path / name, raw / f"{label}_shard_{i}.json")
    for name in ("manifest.json", "baseline_distance_check.csv"):
        source = args.results / "preflight" / name
        destination = raw / ("inputs.json" if name == "manifest.json" else name)
        if name == "manifest.json":
            copy_metadata(source, destination)
        else:
            shutil.copy2(source, destination)
    copy_metadata(args.results / "protocol.json", raw / "protocol.json")
    index = {(r["pair_id"], float(r["detour_ratio"]), r["method"]): r for r in rows}
    assert len(index) == len(rows)
    eligible = []
    for row in rows:
        pair = row["pair_id"]
        if row["method"] == "heat_dose" and float(row["detour_ratio"]) == .2 and all(
                index[(pair, .2, method)]["success"] == "true" for method in METHODS):
            eligible.append((float(index[(pair, .2, "shortest_distance")]["heat_dose"]) -
                             float(row["heat_dose"]), pair))
    target = float(np.median([value for value, _ in eligible]))
    reduction, pair = min(eligible, key=lambda x: (abs(x[0] - target), x[1]))
    shard = int(pair.rsplit("_", 1)[1]) % args.shards
    geometries = json.loads((args.results / f"routes-{shard}/routes.geojson").read_text())
    chosen = [f for f in geometries["features"] if f["properties"]["pair_id"] == pair and
              float(f["properties"]["detour_ratio"]) == .2 and
              f["properties"]["method"] in ("shortest_distance", "heat_dose")]
    assert len(chosen) == 2
    (raw / "selected_routes.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": chosen}) + "\n")
    if args.jobs:
        allocation = subprocess.check_output(["sacct", "-j", args.jobs, "--parsable2",
            "--format=JobID,NodeList,State,Elapsed,AllocCPUS,MaxRSS,ExitCode"], text=True)
        (raw / "slurm_allocation.psv").write_text(allocation)
    source = sorted((ROOT / "src").rglob("*.py")) + [ROOT / name for name in (
        "experiments/run_corrected_validation.py", "experiments/rescore_recorded_paths.py",
        "experiments/run_validation_sensitivity.py", "experiments/export_sampling_validation.py",
        "experiments/export_validation_bundle.py", "scripts/run_sampling_validation.slurm",
        "configs/dc_snapshot_review3466.yaml", "pyproject.toml", "requirements.txt")]
    for path in sorted((ROOT / "src").rglob("*.py")):
        assert digest(path) == manifests[0]["source_sha256"][str(path.relative_to(ROOT))]
    with tarfile.open(asset / "executed_source.tar.gz", "w:gz") as archive:
        for path in source:
            archive.add(path, arcname=str(path.relative_to(ROOT)))
    (asset / "executed_source_manifest.json").write_text(json.dumps(
        {str(p.relative_to(ROOT)): digest(p) for p in source}, indent=2) + "\n")
    provenance = {"python": sys.version,
        "packages": {name: importlib.metadata.version(name) for name in
                     ("networkx", "numpy", "rasterio", "shapely", "pyproj", "PyYAML")},
        "selection_spacing_m": 5, "reference_selection_spacing_m": 20,
        "reporting_spacing_m": 5, "attempts": len(rows), "reference_paths_rescored": len(rescored),
        "source_sha256": manifests[0]["source_sha256"],
        "path_format": "repository-relative",
        "note": "Execution paths are repository-relative; original shard configuration and run identifiers are retained.",
        "selected_case": {"pair_id": pair, "allowance": .2, "delta_H_K": reduction,
                          "target_median_K": target, "common_cases": len(eligible)},
        "files_sha256": {p.name: digest(p) for p in raw.iterdir() if p.name != "provenance.json"}}
    (raw / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    bundle = args.results / "sampling-validation-bundle.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        archive.add(asset, arcname="sampling5")
    print(json.dumps({"bundle": str(bundle), "bytes": bundle.stat().st_size,
                      "sha256": digest(bundle), "selected_case": provenance["selected_case"]}, indent=2))


if __name__ == "__main__":
    main()
