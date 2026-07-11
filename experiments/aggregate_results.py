#!/usr/bin/env python
"""Aggregate raw experiment CSV outputs into paper-ready tables."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routing_backend.experiment_config import load_experiment_config
from routing_backend.experiment_io import ensure_output_layout, read_csv, write_csv, write_markdown
from routing_backend.result_metrics import (
    heat_dose_reduction,
    heat_dose_reduction_percent,
    max_utci_reduction,
    mean_utci_reduction,
    safe_float,
    shade_fraction_increase,
    summarize_by_group,
)


DERIVED_METRICS = [
    "heat_dose_reduction_absolute",
    "heat_dose_reduction_percent",
    "mean_utci_reduction_c",
    "max_utci_reduction_c",
    "shade_fraction_increase",
    "excess_distance_percent",
    "thermal_benefit_per_extra_meter",
    "runtime_ms",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--routes-summary")
    parser.add_argument("--ablations-summary")
    parser.add_argument("--sensitivity-summary")
    args = parser.parse_args()

    config = load_experiment_config(args.config)
    ensure_output_layout(config)
    routes_path = Path(args.routes_summary or config.output_dir / "routes_summary.csv")
    ablations_path = Path(args.ablations_summary or config.output_dir / "ablations_summary.csv")
    sensitivity_path = Path(args.sensitivity_summary or config.output_dir / "sensitivity_summary.csv")

    routes = read_csv(routes_path) if routes_path.exists() else []
    derived_routes = _add_shortest_comparisons(routes)
    success_routes = [row for row in derived_routes if row.get("success", "").lower() == "true"]
    main_table = summarize_by_group(success_routes, ["method"], DERIVED_METRICS)
    detour_table = summarize_by_group(
        [row for row in success_routes if row.get("method") == "proposed_full"],
        ["detour_ratio"],
        DERIVED_METRICS,
    )
    baseline_table = summarize_by_group(success_routes, ["method", "detour_ratio"], DERIVED_METRICS)
    runtime_table = summarize_by_group(success_routes, ["method"], ["runtime_ms"])
    failure_table = _failure_table(routes)

    write_csv(config.output_dir / "tables" / "main_method_comparison.csv", main_table)
    write_csv(config.output_dir / "tables" / "detour_tradeoff.csv", detour_table)
    write_csv(config.output_dir / "tables" / "baseline_comparison.csv", baseline_table)
    write_csv(config.output_dir / "tables" / "runtime_table.csv", runtime_table)
    write_csv(config.output_dir / "tables" / "failure_table.csv", failure_table)

    if ablations_path.exists():
        ablations = _add_shortest_comparisons(read_csv(ablations_path))
        write_csv(
            config.output_dir / "tables" / "ablation_table.csv",
            summarize_by_group([row for row in ablations if row.get("success", "").lower() == "true"], ["method"], DERIVED_METRICS),
        )
    else:
        write_csv(config.output_dir / "tables" / "ablation_table.csv", [])

    sensitivity_note = ""
    if sensitivity_path.exists():
        sensitivity = read_csv(sensitivity_path)
        changed = [
            row
            for row in sensitivity
            if row.get("success", "").lower() == "true" and row.get("route_changed", "").lower() == "true"
        ]
        sensitivity_note = f"\n- Sensitivity rows: {len(sensitivity)}\n- Route-changed rows: {len(changed)}"

    write_markdown(
        config.output_dir / "summary_report.md",
        f"""# Results Summary: {config.study_name}

These tables summarize modeled UTCI/direct-shadow route experiments. They do not report measured human comfort.

- Route rows: {len(routes)}
- Successful route rows: {len(success_routes)}
- Methods in main table: {len(main_table)}
- Detour tradeoff rows: {len(detour_table)}{sensitivity_note}

Primary tables are written under `tables/`.
""",
    )


def _add_shortest_comparisons(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    shortest = {
        (row.get("pair_id"), row.get("detour_ratio")): row
        for row in rows
        if row.get("method") == "shortest_distance" and row.get("success", "").lower() == "true"
    }
    derived: list[dict[str, Any]] = []
    for row in rows:
        output: dict[str, Any] = dict(row)
        base = shortest.get((row.get("pair_id"), row.get("detour_ratio")))
        if base and row.get("success", "").lower() == "true":
            shortest_heat = safe_float(base.get("heat_dose"))
            method_heat = safe_float(row.get("heat_dose"))
            shortest_mean = safe_float(base.get("mean_utci"))
            method_mean = safe_float(row.get("mean_utci"))
            shortest_max = safe_float(base.get("max_utci"))
            method_max = safe_float(row.get("max_utci"))
            shortest_shade = safe_float(base.get("shade_fraction"))
            method_shade = safe_float(row.get("shade_fraction"))
            excess_m = safe_float(row.get("excess_distance_m"))
            heat_reduction = heat_dose_reduction(shortest_heat, method_heat)
            output["heat_dose_reduction_absolute"] = heat_reduction
            output["heat_dose_reduction_percent"] = heat_dose_reduction_percent(shortest_heat, method_heat)
            output["mean_utci_reduction_c"] = mean_utci_reduction(shortest_mean, method_mean)
            output["max_utci_reduction_c"] = max_utci_reduction(shortest_max, method_max)
            output["shade_fraction_increase"] = shade_fraction_increase(shortest_shade, method_shade)
            output["excess_distance_percent"] = (safe_float(row.get("excess_distance_ratio")) or 0.0) * 100.0
            if heat_reduction is not None and excess_m is not None and excess_m > 0:
                output["thermal_benefit_per_extra_meter"] = heat_reduction / excess_m
            else:
                output["thermal_benefit_per_extra_meter"] = None
        derived.append(output)
    return derived


def _failure_table(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        method = row.get("method", "")
        entry = grouped.setdefault(method, {"method": method, "count": 0, "failures": 0, "failure_rate": 0.0})
        entry["count"] += 1
        if row.get("success", "").lower() != "true":
            entry["failures"] += 1
    for entry in grouped.values():
        entry["failure_rate"] = entry["failures"] / entry["count"] if entry["count"] else 0.0
    return sorted(grouped.values(), key=lambda row: row["method"])


if __name__ == "__main__":
    main()
