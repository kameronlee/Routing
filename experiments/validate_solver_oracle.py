#!/usr/bin/env python
"""Compare the router with exhaustive simple-edge-path enumeration on small graphs.

These generated graphs test search behavior, not the DC thermal model. The
enumerator shares the configured edge-cost function but no search/pruning code.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import networkx as nx

from routing_backend.baseline_methods import get_method_config, project_graph_for_method
from routing_backend.route_engine import EdgeFeatures, cost, resource_constrained_routes

BUDGETS = (0.05, 0.10, 0.20, 0.30)
METHODS = ("heat_dose", "proposed_full")
# Disable the wall clock to make the comparison depend only on graph/queue state.
SETTINGS = (("default_counts", 8, 20_000), ("20_expansions", 8, 20),
            ("uncapped_1_label", 1, None), ("uncapped_8_labels", 8, None),
            ("uncapped_32_labels", 32, None))


def add_edge(graph, u, v, rng, *, tradeoff=False):
    length = rng.uniform(40.0, 180.0)
    heat = max(0.0, (180.0 - length) / 14.0 + rng.uniform(-0.5, 0.5)) if tradeoff else rng.uniform(0.0, 12.0)
    features = EdgeFeatures(
        length_m=length, travel_time_s=length / 1.35,
        mean_utci=26.0 + heat, max_utci=26.0 + heat + rng.uniform(0.0, 4.0),
        heat_dose=heat, shade_fraction=rng.random(), scenic_score=rng.random(),
        noise_score=rng.random(), slope=rng.uniform(-0.1, 0.1),
        elevation_change_m=rng.uniform(-2.0, 2.0), uncertainty=rng.random(),
        utci_samples=(26.0 + heat,), shade_source="generated")
    graph.add_edge(u, v, length=length, features=features)


def make_graph(family, rng):
    graph = nx.MultiDiGraph()
    if family == "layered":
        layers = [[0]] + [list(range(1 + 3 * i, 4 + 3 * i)) for i in range(5)] + [[16]]
        for left, right in zip(layers, layers[1:]):
            for u in left:
                for v in right:
                    add_edge(graph, u, v, rng)
                    if rng.random() < 0.15:
                        add_edge(graph, u, v, rng)
        destination = 16
    elif family == "cyclic":
        for u in range(8):
            add_edge(graph, u, u + 1, rng)
        for u in range(9):
            for v in range(9):
                if u != v and rng.random() < 0.25:
                    add_edge(graph, u, v, rng)
        destination = 8
    elif family == "parallel_chain":
        for u in range(10):
            add_edge(graph, u, u + 1, rng, tradeoff=True)
            add_edge(graph, u, u + 1, rng, tradeoff=True)
        destination = 10
    else:
        raise ValueError(family)
    for node in graph:
        graph.nodes[node].update(x=-77.0 + node * 0.0001, y=38.9)
    return graph, 0, destination


def enumerate_paths(graph, origin, destination):
    """Independent DFS: retain every simple path, including parallel-edge choices."""
    paths = []

    def visit(node, seen, edges, distance):
        if node == destination:
            paths.append((tuple(edges), distance))
            return
        for u, v, key, data in graph.out_edges(node, keys=True, data=True):
            if v not in seen:
                visit(v, seen | {v}, edges + [(u, v, key)], distance + data["length"])

    visit(origin, {origin}, [], 0.0)
    return paths


def chain_dynamic_program(choices):
    """Exact cost at each integer distance after choosing one edge per stage."""
    states = {0: 0.0}
    for stage in choices:
        next_states = {}
        for distance, value in states.items():
            for length, edge_cost in stage:
                assert isinstance(length, int) and length > 0
                new_distance, new_cost = distance + length, value + edge_cost
                if new_cost < next_states.get(new_distance, math.inf):
                    next_states[new_distance] = new_cost
        states = next_states
    return states


def stress_checks(count, seed, output):
    """Thirty-two binary choices give 2**32 paths but a compact exact integer DP."""
    rng, rows, snapshots = random.Random(seed), [], []
    for index in range(count):
        graph = nx.MultiDiGraph()
        for node in range(33):
            graph.add_node(node, x=-77 + node * .0001, y=38.9)
        for stage in range(32):
            short = rng.randint(40, 70)
            long = short + rng.randint(10, 50)
            for key, length, heat in ((0, short, rng.uniform(8, 12)), (1, long, rng.uniform(0, 4))):
                graph.add_edge(stage, stage + 1, key=key, length=length, features=EdgeFeatures(
                    length, length / 1.35, 26 + heat, 28 + heat, heat,
                    rng.random(), rng.random(), rng.random(), 0, 0))
        snapshots.append({"graph_id": index, "edges": [{"u": u, "v": v, "key": k,
                           "features": asdict(d["features"])} for u, v, k, d in graph.edges(keys=True, data=True)]})
        baseline = sum(min(graph.edges[i, i + 1, k]["length"] for k in (0, 1)) for i in range(32))
        for method in METHODS:
            projected = project_graph_for_method(graph, method, comfort_threshold=26)
            preference = get_method_config(method, comfort_threshold=26).preference
            choices = [[(projected.edges[i, i + 1, k]["length"], cost(projected.edges[i, i + 1, k]["features"], preference))
                        for k in (0, 1)] for i in range(32)]
            exact = chain_dynamic_program(choices)
            for delta in BUDGETS:
                ceiling = baseline * (1 + delta)
                optimum = min(value for distance, value in exact.items() if distance <= ceiling + 1e-9)
                candidate = resource_constrained_routes(projected, 0, 32, preference, delta=delta,
                    max_candidates=1, max_labels_per_node=8, max_expansions=20_000,
                    max_search_seconds=None, maximum_distance_m=ceiling)[0]
                gap = candidate.cost - optimum
                assert gap >= -1e-8 * max(1, optimum) and candidate.distance_m <= ceiling + 1e-6
                rows.append({"graph_id": index, "method": method, "delta": delta,
                             "oracle_cost": optimum, "candidate_cost": candidate.cost,
                             "relative_gap": max(0.0, gap) / optimum,
                             "matches_oracle": gap <= 1e-8 * max(1, optimum),
                             "route_source": candidate.route_source, "expanded_labels": candidate.expanded_labels,
                             "search_truncated": candidate.search_truncated})
        if (index + 1) % 5 == 0:
            print(f"Stress chains: {index + 1}/{count}", flush=True)
    (output / "stress_graphs.json.gz").write_bytes(gzip.compress(json.dumps(snapshots, separators=(",", ":")).encode(), mtime=0))
    with gzip.open(output / "stress_results.csv.gz", "wt", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {"graphs": count, "seed": seed, "nodes_per_graph": 33, "paths_per_graph": 2 ** 32,
               "cases": len(rows), "matches_oracle": sum(r["matches_oracle"] for r in rows),
               "truncated_cases": sum(r["search_truncated"] for r in rows),
               "mean_relative_gap": sum(r["relative_gap"] for r in rows) / len(rows),
               "max_relative_gap": max(r["relative_gap"] for r in rows),
               "reference": "Independent integer-distance DP; one parallel edge per stage",
               "wall_clock_limit": None, "labels": 8, "expansions": 20000}
    (output / "stress_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-family", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stress-graphs", type=int, default=25)
    parser.add_argument("--output", type=Path, default=ROOT / "paper_assets/review3466/solver_validation")
    args = parser.parse_args()
    if args.per_family < 1:
        parser.error("per-family must be positive")
    rng = random.Random(args.seed)
    args.output.mkdir(parents=True, exist_ok=True)
    rows, snapshots = [], []
    started = perf_counter()
    for family in ("layered", "cyclic", "parallel_chain"):
        for index in range(args.per_family):
            graph, origin, destination = make_graph(family, rng)
            paths = enumerate_paths(graph, origin, destination)
            baseline = min(distance for _, distance in paths)
            graph_id = f"{family}_{index:03d}"
            snapshots.append({"graph_id": graph_id, "origin": origin, "destination": destination,
                              "edges": [{"u": u, "v": v, "key": key, "features": asdict(data["features"])}
                                        for u, v, key, data in graph.edges(keys=True, data=True)]})
            for method in METHODS:
                projected = project_graph_for_method(graph, method, comfort_threshold=26.0)
                preference = get_method_config(method, comfort_threshold=26.0).preference
                scored = [(sum(cost(projected.edges[e]["features"], preference) for e in edges), distance)
                          for edges, distance in paths]
                unconstrained = min(value for value, _ in scored)
                for delta in BUDGETS:
                    ceiling = baseline * (1.0 + delta)
                    feasible = [(value, distance) for value, distance in scored if distance <= ceiling + 1e-9]
                    optimum = min(value for value, _ in feasible)
                    for name, labels, expansions in SETTINGS:
                        candidate = resource_constrained_routes(
                            projected, origin, destination, preference, delta=delta, max_candidates=1,
                            max_labels_per_node=labels, max_expansions=expansions,
                            max_search_seconds=None, maximum_distance_m=ceiling)[0]
                        gap = candidate.cost - optimum
                        tolerance = 1e-8 * max(1.0, abs(optimum))
                        if gap < -tolerance or candidate.distance_m > ceiling + 1e-6:
                            raise AssertionError(f"Invalid candidate: {graph_id}, {method}, {delta}, {name}")
                        rows.append({"graph_id": graph_id, "family": family, "method": method,
                                     "delta": delta, "setting": name, "simple_edge_paths": len(paths),
                                     "feasible_paths": len(feasible), "oracle_cost": optimum,
                                     "unconstrained_cost": unconstrained, "candidate_cost": candidate.cost,
                                     "relative_gap": max(0.0, gap) / max(optimum, 1e-12),
                                     "matches_oracle": gap <= tolerance,
                                     "budget_active": optimum > unconstrained + tolerance,
                                     "route_distance_m": candidate.distance_m, "maximum_distance_m": ceiling,
                                     "route_source": candidate.route_source,
                                     "search_truncated": candidate.search_truncated,
                                     "expanded_labels": candidate.expanded_labels})
        print(f"{family}: {args.per_family} graphs completed", flush=True)
    encoded = (json.dumps(snapshots, separators=(",", ":")) + "\n").encode()
    (args.output / "graphs.json.gz").write_bytes(gzip.compress(encoded, mtime=0))
    with gzip.open(args.output / "oracle_results.csv.gz", "wt", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summaries = []
    for setting, _, _ in SETTINGS:
        selected = [row for row in rows if row["setting"] == setting]
        active = [row for row in selected if row["budget_active"]]
        summaries.append({"setting": setting, "cases": len(selected),
                          "budget_active_cases": len(active),
                          "matches_oracle": sum(row["matches_oracle"] for row in selected),
                          "active_matches_oracle": sum(row["matches_oracle"] for row in active),
                          "truncated_cases": sum(row["search_truncated"] for row in selected),
                          "mean_relative_gap": sum(row["relative_gap"] for row in selected) / len(selected),
                          "max_relative_gap": max(row["relative_gap"] for row in selected)})
    with (args.output / "oracle_summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    metadata = {"seed": args.seed, "graphs_per_family": args.per_family,
                "python": sys.version, "networkx": nx.__version__, "wall_clock_limit": None,
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "graphs_sha256_uncompressed": hashlib.sha256(encoded).hexdigest(),
                "elapsed_seconds": perf_counter() - started, "summary": summaries}
    (args.output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(summaries, indent=2))
    if args.stress_graphs:
        metadata["stress"] = stress_checks(args.stress_graphs, args.seed, args.output)
        metadata["elapsed_seconds"] = perf_counter() - started
        (args.output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(json.dumps(metadata["stress"], indent=2))


if __name__ == "__main__":
    main()
