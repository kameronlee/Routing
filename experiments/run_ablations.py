#!/usr/bin/env python
"""Run routing ablations for the snapshot experiment."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routing_backend.benchmark_runner import run_ablation_benchmark
from routing_backend.experiment_config import load_experiment_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--od-pairs")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--detour-ratio", type=float)
    args = parser.parse_args()

    config = load_experiment_config(args.config)
    outputs = run_ablation_benchmark(
        config,
        od_pairs_path=args.od_pairs or config.output_dir / "od_pairs.csv",
        limit=args.limit,
        detour_ratio=args.detour_ratio,
    )
    _maybe_plot_ablation(config)
    for name, path in outputs.items():
        print(f"{name}: {path}")


def _maybe_plot_ablation(config) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    import csv

    path = config.output_dir / "ablations_summary.csv"
    if not path.exists():
        return
    rows = [row for row in csv.DictReader(path.open(encoding="utf-8")) if row.get("success") == "true"]
    by_method: dict[str, list[float]] = {}
    shortest_by_pair = {
        (row["pair_id"], row["detour_ratio"]): float(row["heat_dose"])
        for row in rows
        if row["method"] == "shortest_distance" and row.get("heat_dose")
    }
    for row in rows:
        if not row.get("heat_dose"):
            continue
        baseline = shortest_by_pair.get((row["pair_id"], row["detour_ratio"]))
        if baseline is None:
            continue
        by_method.setdefault(row["method"], []).append(baseline - float(row["heat_dose"]))
    if not by_method:
        return
    methods = sorted(by_method)
    values = [sum(by_method[method]) / len(by_method[method]) for method in methods]
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    ax.bar(methods, values)
    ax.set_title("Ablation heat-dose reduction vs shortest route")
    ax.set_ylabel("Mean heat-dose reduction")
    ax.tick_params(axis="x", rotation=35)
    fig.savefig(config.output_dir / "figures" / "ablation_heat_reduction.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
