#!/usr/bin/env python
"""Validate frozen inputs or rerun the corrected DC experiment on fixed OD pairs."""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import networkx as nx
import rasterio

from routing_backend.benchmark_runner import load_experiment_graph, run_route_benchmark
from routing_backend.experiment_config import load_experiment_config

METHODS = ["shortest_distance", "azimuth_heuristic", "shadow_only", "heat_dose", "proposed_full"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["preflight", "routes"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args()
    if args.shards < 1 or not 0 <= args.shard < args.shards:
        parser.error("require 0 <= shard < shards")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = load_experiment_config(ROOT / "configs/dc_snapshot_review3466.yaml")
    config = replace(config, output_dir=output)
    config.require_existing_inputs()
    od_path = ROOT / "paper_assets/review3466/raw/od_pairs.csv"
    with od_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        all_pairs = list(reader)
    metadata = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "stage": args.stage, "python": sys.version, "platform": platform.platform(),
        "networkx": nx.__version__, "rasterio": rasterio.__version__,
        "git_commit": os.environ.get("ROUTING_CODE_COMMIT", "unrecorded"),
        "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in sorted((ROOT / "src").rglob("*.py"))},
        "runner_sha256": sha256(Path(__file__)), "od_pairs_sha256": sha256(od_path),
        "config": config.to_dict(), "limit": args.limit,
        "shard": args.shard, "shards": args.shards, "method_order": METHODS,
    }
    if args.stage == "preflight":
        paths = [config.graph_path, config.utci_raster_path, config.shadow_raster_path,
                 config.dem_raster_path, *config.canopy_raster_paths,
                 *config.landcover_raster_paths, *config.building_height_raster_paths,
                 config.traffic_geojson_path]
        metadata["inputs"] = {str(p.relative_to(ROOT)): {"bytes": p.stat().st_size,
                               "sha256": sha256(p)} for p in paths}
        for p in (config.utci_raster_path, config.shadow_raster_path):
            with rasterio.open(p) as raster:
                metadata["inputs"][str(p.relative_to(ROOT))]["raster"] = {
                    "shape": raster.shape, "bounds": tuple(raster.bounds),
                    "crs": str(raster.crs), "nodata": raster.nodata}
        graph = load_experiment_graph(config)
        metadata["graph_nodes"] = len(graph)
        metadata["graph_edges"] = graph.number_of_edges()
        checks = []
        for pair in all_pairs:
            origin = pair["origin_node"]
            destination = pair["destination_node"]
            origin = origin if origin in graph else int(origin)
            destination = destination if destination in graph else int(destination)
            actual = nx.shortest_path_length(graph, origin, destination, weight="length")
            expected = float(pair["baseline_shortest_distance_m"])
            checks.append({"pair_id": pair["pair_id"], "archived_distance_m": expected,
                           "recomputed_distance_m": actual, "error_m": actual - expected})
        with (output / "baseline_distance_check.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(checks[0]))
            writer.writeheader()
            writer.writerows(checks)
        metadata["baseline_max_abs_error_m"] = max(abs(row["error_m"]) for row in checks)
        metadata["baseline_pairs_checked"] = len(checks)
        (output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
        if metadata["baseline_max_abs_error_m"] > 1e-4:
            raise RuntimeError("Recovered graph does not reproduce the archived baseline distances")
        print(json.dumps({k: metadata[k] for k in ("graph_nodes", "graph_edges",
                         "baseline_pairs_checked", "baseline_max_abs_error_m")}), flush=True)
        return
    selected = all_pairs[:args.limit] if args.limit is not None else all_pairs
    selected = selected[args.shard::args.shards]
    selected_path = output / "od_pairs.csv"
    with selected_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected)
    metadata["selected_od_pairs_sha256"] = sha256(selected_path)
    metadata["selected_pair_count"] = len(selected)
    (output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    started = time.monotonic()
    print(f"Starting {len(selected)} pairs; four budgets; five methods", flush=True)
    run_route_benchmark(config, od_pairs_path=selected_path, methods=METHODS,
                        run_id=f"corrected-20261029-shard{args.shard}of{args.shards}")
    metadata["elapsed_seconds"] = time.monotonic() - started
    metadata["finished_utc"] = datetime.now(timezone.utc).isoformat()
    metadata["outputs"] = {p.name: sha256(p) for p in output.iterdir()
                           if p.is_file() and p.name != "manifest.json"}
    (output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Finished in {metadata['elapsed_seconds']:.1f} s", flush=True)


if __name__ == "__main__":
    main()
