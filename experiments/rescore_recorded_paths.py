#!/usr/bin/env python
"""Score frozen paths on a common sampling field without rerouting them."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from routing_backend.baseline_methods import _edge_id_to_traversal, get_method_config
from routing_backend.benchmark_runner import (
    _build_feature_graph_for_pair, _coerce_node_id, build_real_feature_context,
    load_experiment_graph, load_od_pairs,
)
from routing_backend.experiment_config import load_experiment_config
from routing_backend.experiment_io import write_csv
from routing_backend.paired_comparison import succeeded
from routing_backend.route_engine import summarize_route


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-spacing", type=float, default=5.0)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.shards < 1 or not 0 <= args.shard < args.shards:
        parser.error("require 0 <= shard < shards")
    if not 0 < args.sample_spacing < float("inf"):
        parser.error("sample spacing must be finite and positive")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = replace(load_experiment_config(ROOT / "configs/dc_snapshot_review3466.yaml"),
                     output_dir=output, sample_spacing_m=args.sample_spacing)
    config.require_existing_inputs()
    pairs = load_od_pairs(ROOT / "paper_assets/review3466/raw/od_pairs.csv", limit=args.limit)
    pairs = pairs[args.shard::args.shards]
    reference = args.reference.resolve()
    opener = gzip.open if reference.suffix == ".gz" else open
    with opener(reference, "rt", newline="") as stream:
        rows = list(csv.DictReader(stream))
    groups = defaultdict(list)
    for row in rows:
        groups[(row["pair_id"], float(row["detour_ratio"]))].append(row)
    graph = load_experiment_graph(config)
    context = build_real_feature_context(config)
    cache, checked = {}, []
    preference = get_method_config("proposed_full", comfort_threshold=26.0).preference
    metadata = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "config": config.to_dict(), "shard": args.shard, "shards": args.shards,
        "pair_ids": [p["pair_id"] for p in pairs],
        "purpose": "Same-path scoring at the reporting spacing; no path selection.",
    }
    (output / "rescore_manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    started = time.monotonic()
    try:
        for pair in pairs:
            origin = _coerce_node_id(graph, pair["origin_node"])
            destination = _coerce_node_id(graph, pair["destination_node"])
            for allowance in config.detour_ratios:
                ceiling = float(pair["baseline_shortest_distance_m"]) * (1 + allowance)
                dense = _build_feature_graph_for_pair(
                    graph, origin, destination, ceiling, config=config, context=context,
                    cache=cache, sample_spacing_m=config.sample_spacing_m,
                    comfort_threshold=config.comfort_threshold_c)
                selected = groups[(pair["pair_id"], allowance)]
                if len(selected) != 5 or len({r["method"] for r in selected}) != 5:
                    raise ValueError(f"Incomplete reference case: {pair['pair_id']}, {allowance}")
                for row in selected:
                    result = {
                        "pair_id": pair["pair_id"], "detour_ratio": allowance,
                        "method": row["method"], "route_success": row["success"],
                        "rescore_success": False, "H_selection_K": row["heat_dose"],
                        "H_reporting_K": None, "J_reporting_K_m": None,
                        "distance_m": row["route_distance_m"], "error": "",
                    }
                    if succeeded(row):
                        try:
                            path = [_edge_id_to_traversal(dense, edge)
                                    for edge in json.loads(row["edge_ids"])]
                            candidate = summarize_route(dense, path, preference)
                            if abs(candidate.distance_m - float(row["route_distance_m"])) > 1e-6:
                                raise ValueError("Recorded path length changed during rescoring")
                            result.update(rescore_success=True, H_reporting_K=candidate.heat_dose,
                                          J_reporting_K_m=candidate.distance_m * candidate.heat_dose)
                        except (ValueError, KeyError) as exc:
                            result["error"] = f"{type(exc).__name__}: {exc}"
                    checked.append(result)
            print(f"Scored {pair['pair_id']}; {len(checked)} paths", flush=True)
    finally:
        context.close()
    destination = output / "reference_rescored.csv"
    write_csv(destination, checked, list(checked[0]))
    metadata.update(elapsed_seconds=time.monotonic() - started,
                    finished_utc=datetime.now(timezone.utc).isoformat(),
                    rows=len(checked),
                    successes=sum(r["rescore_success"] for r in checked),
                    output_sha256=hashlib.sha256(destination.read_bytes()).hexdigest())
    (output / "rescore_manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({k: metadata[k] for k in ("rows", "successes", "elapsed_seconds")}))


if __name__ == "__main__":
    main()
