#!/usr/bin/env python
"""Run focused proposed_full weight tuning variants on a small OD subset."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routing_backend.benchmark_runner import (
    ROUTE_SUMMARY_COLUMNS,
    _build_feature_graph_for_pair,
    _candidate_row,
    _coerce_node_id,
    _failure_row,
    build_real_feature_context,
    load_experiment_graph,
    load_od_pairs,
)
from routing_backend.experiment_config import load_experiment_config
from routing_backend.experiment_io import config_hash, ensure_output_layout, write_csv, write_markdown
from routing_backend.preferences import Preference
from routing_backend.route_engine import resource_constrained_routes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--od-pairs")
    parser.add_argument("--subset-size", type=int, default=100)
    parser.add_argument("--detour-ratios", default="0.10,0.20")
    args = parser.parse_args()

    config = load_experiment_config(args.config)
    config.require_existing_inputs()
    ensure_output_layout(config)
    pairs = load_od_pairs(args.od_pairs or config.output_dir / "od_pairs.csv", limit=args.subset_size)
    detour_ratios = [float(value.strip()) for value in args.detour_ratios.split(",") if value.strip()]
    if not detour_ratios:
        raise ValueError("--detour-ratios must contain at least one value")

    graph = load_experiment_graph(config)
    context = build_real_feature_context(config, use_shadow=True)
    cache: dict[tuple[Any, ...], Any] = {}
    hash_value = config_hash(config)
    variants = _variant_preferences(config.comfort_threshold_c)
    rows: list[dict[str, Any]] = []

    try:
        for pair in pairs:
            origin_node = _coerce_node_id(graph, pair["origin_node"])
            destination_node = _coerce_node_id(graph, pair["destination_node"])
            baseline_distance_m = float(pair["baseline_shortest_distance_m"])
            for detour_ratio in detour_ratios:
                maximum_distance_m = baseline_distance_m * (1.0 + detour_ratio)
                try:
                    feature_graph = _build_feature_graph_for_pair(
                        graph,
                        origin_node,
                        destination_node,
                        maximum_distance_m,
                        config=config,
                        context=context,
                        cache=cache,
                        sample_spacing_m=config.sample_spacing_m,
                        comfort_threshold=config.comfort_threshold_c,
                    )
                except Exception as exc:
                    rows.extend(
                        _failure_row(
                            config,
                            pair=pair,
                            method=name,
                            detour_ratio=detour_ratio,
                            baseline_distance_m=baseline_distance_m,
                            runtime_ms=0.0,
                            failure_reason=str(exc),
                            config_hash_value=hash_value,
                            run_id=hash_value,
                        )
                        | {"variant_notes": notes}
                        for name, _preference, notes in variants
                    )
                    continue

                for name, preference, notes in variants:
                    started = perf_counter()
                    try:
                        candidate = resource_constrained_routes(
                            feature_graph,
                            origin_node,
                            destination_node,
                            preference,
                            delta=detour_ratio,
                            max_candidates=1,
                            max_labels_per_node=config.route_search_labels_per_node,
                            max_expansions=config.route_search_expansions,
                            max_seconds=config.route_search_seconds,
                            departure_time=config.departure_time,
                            utci_raster_path=str(config.utci_raster_path),
                        )[0]
                        rows.append(
                            _candidate_row(
                                config,
                                pair=pair,
                                method=name,
                                detour_ratio=detour_ratio,
                                candidate=candidate,
                                baseline_distance_m=baseline_distance_m,
                                runtime_ms=(perf_counter() - started) * 1000.0,
                                success=True,
                                failure_reason="",
                                config_hash_value=hash_value,
                                run_id=hash_value,
                            )
                            | {"variant_notes": notes}
                        )
                    except Exception as exc:
                        rows.append(
                            _failure_row(
                                config,
                                pair=pair,
                                method=name,
                                detour_ratio=detour_ratio,
                                baseline_distance_m=baseline_distance_m,
                                runtime_ms=(perf_counter() - started) * 1000.0,
                                failure_reason=str(exc),
                                config_hash_value=hash_value,
                                run_id=hash_value,
                            )
                            | {"variant_notes": notes}
                        )
    finally:
        context.close()

    output = config.output_dir / "proposed_tuning_summary.csv"
    write_csv(output, rows, ROUTE_SUMMARY_COLUMNS + ["variant_notes"])
    report = _tuning_report(config.study_name, rows, detour_ratios)
    write_markdown(config.output_dir / "proposed_tuning_report.md", report)
    print(f"proposed_tuning_summary: {output}")
    print(f"proposed_tuning_report: {config.output_dir / 'proposed_tuning_report.md'}")


def _variant_preferences(comfort_threshold: float) -> list[tuple[str, Preference, str]]:
    base = Preference(
        weight_cool=1.0,
        weight_scenic=0.45,
        weight_quiet=0.45,
        weight_slope=0.35,
        weight_time=0.20,
        weight_distance=0.15,
        weight_shade=1.0,
        uncertainty_penalty=0.15,
        comfort_threshold=comfort_threshold,
    )
    return [
        ("proposed_full_v1_current", base, "Current balanced proposed_full weights."),
        (
            "proposed_full_v2_heat_heavy",
            base.with_overrides(
                weight_cool=1.8,
                weight_scenic=0.25,
                weight_quiet=0.25,
                weight_slope=0.20,
                weight_time=0.12,
                weight_distance=0.08,
            ),
            "Increases thermal cost and reduces non-thermal terms.",
        ),
        (
            "proposed_full_v3_shade_heavy",
            base.with_overrides(
                weight_cool=1.4,
                weight_shade=2.2,
                weight_scenic=0.25,
                weight_quiet=0.25,
                weight_slope=0.20,
                weight_time=0.12,
                weight_distance=0.08,
            ),
            "Increases direct shade penalty within the thermal objective.",
        ),
        (
            "proposed_full_v4_heat_low_distance_penalty",
            base.with_overrides(
                weight_cool=2.0,
                weight_shade=1.5,
                weight_scenic=0.20,
                weight_quiet=0.20,
                weight_slope=0.15,
                weight_time=0.05,
                weight_distance=0.03,
            ),
            "Emphasizes heat and shade while reducing distance/time penalties.",
        ),
    ]


def _tuning_report(study_name: str, rows: list[dict[str, Any]], detour_ratios: list[float]) -> str:
    successes = [row for row in rows if str(row.get("success", "")).lower() == "true"]
    failures = [row for row in rows if str(row.get("success", "")).lower() != "true"]
    lines = [
        f"# Proposed-Full Tuning Report: {study_name}",
        "",
        f"- Route rows: {len(rows)}",
        f"- Successful route rows: {len(successes)}",
        f"- Failed route rows: {len(failures)}",
        "- Detour ratios: " + ", ".join(str(value) for value in detour_ratios),
        "",
        "## Variant Means",
        "",
        "| variant | successes | failures | mean heat dose | mean UTCI | mean shade | mean excess distance |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    variants = sorted({str(row.get("method", "")) for row in rows})
    for variant in variants:
        variant_successes = [row for row in successes if row.get("method") == variant]
        variant_failures = [row for row in failures if row.get("method") == variant]
        lines.append(
            "| {variant} | {successes} | {failures} | {heat_dose} | {mean_utci} | {shade} | {excess} |".format(
                variant=variant,
                successes=len(variant_successes),
                failures=len(variant_failures),
                heat_dose=_mean_cell(variant_successes, "heat_dose"),
                mean_utci=_mean_cell(variant_successes, "mean_utci"),
                shade=_mean_cell(variant_successes, "shade_fraction"),
                excess=_mean_cell(variant_successes, "excess_distance_ratio"),
            )
        )
    return "\n".join(lines)


def _mean_cell(rows: list[dict[str, Any]], key: str) -> str:
    values = [float(row[key]) for row in rows if row.get(key) not in (None, "")]
    if not values:
        return ""
    return f"{sum(values) / len(values):.4f}"


if __name__ == "__main__":
    main()
