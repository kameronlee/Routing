#!/usr/bin/env python
"""Run sensitivity and uncertainty experiments."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routing_backend.benchmark_runner import run_sensitivity_benchmark
from routing_backend.experiment_config import load_experiment_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--od-pairs")
    parser.add_argument("--subset-size", type=int, default=200)
    parser.add_argument("--detour-ratio", type=float)
    args = parser.parse_args()

    config = load_experiment_config(args.config)
    outputs = run_sensitivity_benchmark(
        config,
        od_pairs_path=args.od_pairs or config.output_dir / "od_pairs.csv",
        subset_size=args.subset_size,
        detour_ratio=args.detour_ratio,
    )
    _maybe_plot_sensitivity(config)
    for name, path in outputs.items():
        print(f"{name}: {path}")


def _maybe_plot_sensitivity(config) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    import csv

    path = config.output_dir / "sensitivity_summary.csv"
    if not path.exists():
        return
    rows = [row for row in csv.DictReader(path.open(encoding="utf-8")) if row.get("success") == "true"]
    by_method: dict[str, list[float]] = {}
    for row in rows:
        if row.get("edge_jaccard_overlap"):
            by_method.setdefault(row["method"], []).append(float(row["edge_jaccard_overlap"]))
    if not by_method:
        return
    labels = sorted(by_method)
    values = [sum(by_method[label]) / len(by_method[label]) for label in labels]
    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    ax.bar(labels, values)
    ax.set_title("Sensitivity summary: mean route edge Jaccard overlap")
    ax.set_ylabel("Jaccard overlap")
    ax.set_ylim(0, 1)
    ax.tick_params(axis="x", rotation=45)
    fig.savefig(config.output_dir / "figures" / "sensitivity_heatmap.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
