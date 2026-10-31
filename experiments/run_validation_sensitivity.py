#!/usr/bin/env python
"""Fixed-cohort one-factor checks, with every selected path also scored at 5 m."""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
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
from routing_backend.review_sensitivity import run_review_sensitivity
from routing_backend.route_engine import summarize_route


def protocol():
    variants = [("reference", {})]
    defaults = get_method_config("proposed_full", comfort_threshold=26.0).preference
    # One coefficient changes at a time; distance/time terms remain fixed.
    for field in ("weight_cool", "weight_shade", "weight_scenic", "weight_quiet", "weight_slope"):
        for factor in (0.0, 2.0):
            variants.append((f"{field}_x{factor:g}", {
                "preference_overrides": {field: getattr(defaults, field) * factor}}))
    variants += [(f"threshold_{threshold}C", {"threshold": threshold}) for threshold in (24, 28)]
    variants += [(f"sampling_{spacing}m", {"spacing": spacing}) for spacing in (5, 10, 40)]
    return variants


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--subset-size", type=int, default=100)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args()
    if args.subset_size < 1 or args.shards < 1 or not 0 <= args.shard < args.shards:
        parser.error("invalid subset or shard")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    pairs = load_od_pairs(ROOT / "paper_assets/review3466/raw/od_pairs.csv", limit=args.subset_size)
    pairs = pairs[args.shard::args.shards]
    od_path = output / "od_pairs.csv"
    write_csv(od_path, pairs, list(pairs[0]))
    config = replace(load_experiment_config(ROOT / "configs/dc_snapshot_review3466.yaml"),
                     output_dir=output, detour_ratios=(0.20,))
    metadata = {"protocol": protocol(), "selected_pair_ids": [p["pair_id"] for p in pairs],
                "config": config.to_dict(), "reporting_spacing_m": 20, "dense_check_spacing_m": 5,
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "reference_role": "5 m is a numerical comparator, not ground truth"}
    (output / "validation_protocol.json").write_text(json.dumps(metadata, indent=2) + "\n")
    started = time.monotonic()
    summary = run_review_sensitivity(config, od_pairs_path=od_path,
                                     subset_size=len(pairs), variant_settings=protocol())
    print(f"Reroutes complete after {time.monotonic() - started:.1f} s", flush=True)
    with summary.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    graph = load_experiment_graph(config)
    context = build_real_feature_context(config)
    cache, checked = {}, []
    preference = get_method_config("proposed_full", comfort_threshold=26.0).preference
    try:
        for pair in pairs:
            origin = _coerce_node_id(graph, pair["origin_node"])
            destination = _coerce_node_id(graph, pair["destination_node"])
            ceiling = float(pair["baseline_shortest_distance_m"]) * 1.20
            dense_graph = _build_feature_graph_for_pair(
                graph, origin, destination, ceiling, config=config, context=context,
                cache=cache, sample_spacing_m=5.0, comfort_threshold=26.0)
            for row in rows:
                if row["pair_id"] != pair["pair_id"]:
                    continue
                result = {"pair_id": pair["pair_id"], "method": row["method"],
                          "route_success": row["success"], "dense_success": False,
                          "H_20m_K": row["heat_dose"], "H_selection_spacing_K": row["variant_spacing_heat_dose"],
                          "H_5m_K": None, "J_5m_K_m": None, "distance_m": row["route_distance_m"],
                          "error": ""}
                if row["success"].lower() in ("true", "1"):
                    try:
                        ids = json.loads(row["edge_ids"])
                        selected = summarize_route(dense_graph,
                            [_edge_id_to_traversal(dense_graph, e) for e in ids], preference)
                        result.update(dense_success=True, H_5m_K=selected.heat_dose,
                                      J_5m_K_m=selected.distance_m * selected.heat_dose)
                    except (ValueError, KeyError) as exc:
                        result["error"] = f"{type(exc).__name__}: {exc}"
                checked.append(result)
    finally:
        context.close()
    write_csv(output / "dense_path_check.csv", checked, list(checked[0]))
    metadata["elapsed_seconds"] = time.monotonic() - started
    (output / "validation_protocol.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Dense checks complete after {metadata['elapsed_seconds']:.1f} s", flush=True)


if __name__ == "__main__":
    main()
