#!/usr/bin/env python
"""Freeze corrected-run records and the two geometries needed for the paper map."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
METHODS = ["shortest_distance", "azimuth_heuristic", "shadow_only", "heat_dose", "proposed_full"]


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def freeze_csv(paths, output, expected):
    rows, fields = [], None
    for path in paths:
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            if fields is None:
                fields = reader.fieldnames
            assert fields == reader.fieldnames
            rows.extend(reader)
    assert len(rows) == expected, (output.name, len(rows), expected)
    rows.sort(key=lambda r: (r["pair_id"], float(r.get("detour_ratio", .2)), r["method"]))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    output.write_bytes(gzip.compress(stream.getvalue().encode(), mtime=0))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-job", default="")
    parser.add_argument("--sensitivity-job", default="")
    args = parser.parse_args()
    output = ROOT / "paper_assets/review3466/corrected/raw"
    output.mkdir(parents=True, exist_ok=True)
    main_dirs = [ROOT / f"results/review3466-final-{i}" for i in range(8)]
    sensitivity_dirs = [ROOT / f"results/review3466-final-sensitivity-{i}" for i in range(2)]
    manifests = []
    for index, directory in enumerate(main_dirs):
        manifest = json.loads((directory / "manifest.json").read_text())
        assert manifest["finished_utc"]
        for name, expected in manifest["outputs"].items():
            assert digest(directory / name) == expected, (directory, name)
        manifests.append(manifest)
        shutil.copyfile(directory / "manifest.json", output / f"main_shard_{index}.json")
    assert all(m["source_sha256"] == manifests[0]["source_sha256"] for m in manifests)
    rows = freeze_csv([p / "routes_summary.csv" for p in main_dirs], output / "routes_summary.csv.gz", 10000)
    sensitivity = freeze_csv([p / "review_sensitivity_summary.csv" for p in sensitivity_dirs],
                             output / "review_sensitivity_summary.csv.gz", 1600)
    freeze_csv([p / "dense_path_check.csv" for p in sensitivity_dirs], output / "dense_path_check.csv.gz", 1600)
    for index, directory in enumerate(sensitivity_dirs):
        shutil.copyfile(directory / "validation_protocol.json", output / f"sensitivity_shard_{index}.json")
        shutil.copyfile(directory / "review_sensitivity_protocol.json", output / f"sensitivity_reporting_{index}.json")
    shutil.copyfile(ROOT / "results/review3466-height-preflight/manifest.json", output / "inputs.json")
    shutil.copyfile(ROOT / "results/review3466-height-preflight/baseline_distance_check.csv", output / "baseline_distance_check.csv")
    shutil.copyfile(ROOT / "data/processed/rasters/building_height_1m.json", output / "building_height_derivation.json")
    for name in ("raster_stats.csv", "raster_metadata.json", "raster_alignment_report.md"):
        shutil.copyfile(ROOT / "results/review3466-raster-qc" / name, output / name)
    index = {(r["pair_id"], float(r["detour_ratio"]), r["method"]): r for r in rows}
    eligible = []
    for row in rows:
        pair = row["pair_id"]
        if row["method"] == "heat_dose" and float(row["detour_ratio"]) == .2 and all(
            index[(pair, .2, method)]["success"] == "true" for method in METHODS):
            eligible.append((float(index[(pair, .2, "shortest_distance")]["heat_dose"]) - float(row["heat_dose"]), pair))
    target = float(np.quantile([value for value, _ in eligible], .5))
    reduction, pair = min(eligible, key=lambda item: (abs(item[0] - target), item[1]))
    shard = int(pair.rsplit("_", 1)[1]) % 8
    geometries = json.loads((main_dirs[shard] / "routes.geojson").read_text())
    selected = [f for f in geometries["features"] if f["properties"]["pair_id"] == pair and
                float(f["properties"]["detour_ratio"]) == .2 and
                f["properties"]["method"] in ("shortest_distance", "heat_dose")]
    assert len(selected) == 2
    (output / "selected_routes.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": selected}, separators=(",", ":")) + "\n")
    versions = {}
    for name in ("networkx", "numpy", "rasterio", "shapely", "pyproj", "osmnx", "PyYAML", "geopandas"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    allocation = ""
    if args.main_job and args.sensitivity_job:
        try:
            allocation = subprocess.check_output(["sacct", "-j", f"{args.main_job},{args.sensitivity_job}",
                "--parsable2", "--format=JobID,NodeList,State,Elapsed,AllocCPUS,MaxRSS,ExitCode"], text=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
    (output / "slurm_allocation.psv").write_text(allocation)
    provenance = {"python": sys.version, "packages": versions,
                  "source_sha256": manifests[0]["source_sha256"],
                  "selected_case": {"pair_id": pair, "allowance": .2, "delta_H_K": reduction,
                      "target_median_K": target, "common_cases": len(eligible), "source_shard": shard},
                  "note": "Frozen outputs retain each original shard configuration and run identifier.",
                  "files_sha256": {p.name: digest(p) for p in output.iterdir() if p.is_file() and p.name != "provenance.json"}}
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    archive = ROOT / "results/review3466-final-bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(output, arcname="raw")
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size,
                      "sha256": digest(archive), "selected_case": provenance["selected_case"]}, indent=2))


if __name__ == "__main__":
    main()
