#!/usr/bin/env python
"""Generate publication-oriented figures from experiment CSV outputs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routing_backend.experiment_config import load_experiment_config
from routing_backend.experiment_io import ensure_output_layout, read_csv
from routing_backend.result_metrics import heat_dose_reduction, mean_utci_reduction, safe_float, shade_fraction_increase


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--routes-summary")
    parser.add_argument("--ablations-summary")
    parser.add_argument("--sensitivity-summary")
    args = parser.parse_args()

    try:
        import matplotlib.pyplot as plt  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("matplotlib is required for figure generation. Install the experiments extra.") from exc

    config = load_experiment_config(args.config)
    ensure_output_layout(config)
    routes = read_csv(args.routes_summary or config.output_dir / "routes_summary.csv")
    enriched = _with_baseline_metrics(routes)
    _line_by_detour(
        config,
        enriched,
        "heat_dose_reduction",
        "detour_vs_heat_dose_reduction.png",
        "Detour vs modeled heat-dose reduction",
        "Heat-dose reduction",
    )
    _line_by_detour(
        config,
        enriched,
        "mean_utci_reduction",
        "detour_vs_mean_utci_reduction.png",
        "Detour vs mean UTCI reduction",
        "Mean UTCI reduction (C)",
    )
    _line_by_detour(
        config,
        enriched,
        "shade_fraction_increase",
        "detour_vs_shade_fraction.png",
        "Detour vs shade-fraction increase",
        "Shade-fraction increase",
    )
    _histogram(
        config,
        enriched,
        lambda row: safe_float(row.get("excess_distance_ratio")),
        "excess_distance_distribution.png",
        "Excess distance distribution",
        "Excess distance ratio",
    )
    _boxplot_by_method(
        config,
        enriched,
        "heat_dose_reduction",
        "method_comparison_boxplot.png",
        "Modeled heat-dose reduction by method",
        "Heat-dose reduction",
    )
    _boxplot_by_method(
        config,
        enriched,
        "runtime_ms",
        "runtime_distribution.png",
        "Runtime by method",
        "Runtime (ms)",
    )
    ablations_path = Path(args.ablations_summary or config.output_dir / "ablations_summary.csv")
    if ablations_path.exists():
        _boxplot_by_method(
            config,
            _with_baseline_metrics(read_csv(ablations_path)),
            "heat_dose_reduction",
            "ablation_comparison.png",
            "Ablation heat-dose reduction",
            "Heat-dose reduction",
        )
    sensitivity_path = Path(args.sensitivity_summary or config.output_dir / "sensitivity_summary.csv")
    if sensitivity_path.exists():
        _boxplot_by_method(
            config,
            read_csv(sensitivity_path),
            "edge_jaccard_overlap",
            "sensitivity_summary.png",
            "Sensitivity route overlap",
            "Edge Jaccard overlap",
        )


def _with_baseline_metrics(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    shortest = {
        (row.get("pair_id"), row.get("detour_ratio")): row
        for row in rows
        if row.get("method") == "shortest_distance" and row.get("success", "").lower() == "true"
    }
    enriched: list[dict[str, str]] = []
    for row in rows:
        output = dict(row)
        base = shortest.get((row.get("pair_id"), row.get("detour_ratio")))
        if base and row.get("success", "").lower() == "true":
            output["heat_dose_reduction"] = str(heat_dose_reduction(safe_float(base.get("heat_dose")), safe_float(row.get("heat_dose"))) or 0.0)
            output["mean_utci_reduction"] = str(mean_utci_reduction(safe_float(base.get("mean_utci")), safe_float(row.get("mean_utci"))) or 0.0)
            output["shade_fraction_increase"] = str(shade_fraction_increase(safe_float(base.get("shade_fraction")), safe_float(row.get("shade_fraction"))) or 0.0)
        enriched.append(output)
    return enriched


def _line_by_detour(config, rows: list[dict[str, str]], metric: str, filename: str, title: str, ylabel: str) -> None:
    import matplotlib.pyplot as plt

    grouped: dict[str, dict[float, list[float]]] = {}
    for row in rows:
        if row.get("success", "").lower() != "true":
            continue
        value = safe_float(row.get(metric))
        detour = safe_float(row.get("detour_ratio"))
        if value is None or detour is None:
            continue
        grouped.setdefault(row.get("method", ""), {}).setdefault(detour, []).append(value)
    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    for method, values_by_detour in sorted(grouped.items()):
        xs = sorted(values_by_detour)
        ys = [sum(values_by_detour[x]) / len(values_by_detour[x]) for x in xs]
        ax.plot(xs, ys, marker="o", label=method)
    ax.set_title(title)
    ax.set_xlabel("Allowed detour ratio")
    ax.set_ylabel(ylabel)
    ax.legend(fontsize=8)
    fig.savefig(config.output_dir / "figures" / filename, dpi=300)
    plt.close(fig)


def _histogram(config, rows: list[dict[str, str]], value_fn: Callable[[dict[str, str]], float | None], filename: str, title: str, xlabel: str) -> None:
    import matplotlib.pyplot as plt

    values = [value for row in rows if (value := value_fn(row)) is not None and row.get("success", "").lower() == "true"]
    if not values:
        return
    fig, ax = plt.subplots(figsize=(7, 5), constrained_layout=True)
    ax.hist(values, bins=30, color="#3b6ea8", alpha=0.85)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Route count")
    fig.savefig(config.output_dir / "figures" / filename, dpi=300)
    plt.close(fig)


def _boxplot_by_method(config, rows: list[dict[str, str]], metric: str, filename: str, title: str, ylabel: str) -> None:
    import matplotlib.pyplot as plt

    grouped: dict[str, list[float]] = {}
    for row in rows:
        if row.get("success", "").lower() != "true":
            continue
        value = safe_float(row.get(metric))
        if value is not None:
            grouped.setdefault(row.get("method", ""), []).append(value)
    grouped = {method: values for method, values in grouped.items() if values}
    if not grouped:
        return
    labels = sorted(grouped)
    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    ax.boxplot([grouped[label] for label in labels], labels=labels, showfliers=False)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", rotation=35)
    fig.savefig(config.output_dir / "figures" / filename, dpi=300)
    plt.close(fig)


if __name__ == "__main__":
    main()
