"""Remote visual audit exports for route benchmark outputs."""

from __future__ import annotations

import json
from pathlib import Path
import random
from typing import Any

from routing_backend.experiment_config import ExperimentConfig
from routing_backend.experiment_io import ensure_output_layout, read_csv, write_csv, write_json, write_markdown
from routing_backend.result_metrics import safe_float


AUDIT_COLUMNS = [
    "case_id",
    "pair_id",
    "selection_reason",
    "shortest_heat_dose",
    "proposed_heat_dose",
    "heat_dose_reduction_percent",
    "shortest_distance_m",
    "proposed_distance_m",
    "detour_ratio",
]


def export_visual_audit_cases(
    config: ExperimentConfig,
    *,
    routes_summary_path: str | Path,
    routes_geojson_path: str | Path,
    count: int = 12,
) -> dict[str, Path]:
    """Select and export benchmark cases for remote plausibility inspection."""

    ensure_output_layout(config)
    rows = [row for row in read_csv(routes_summary_path) if row.get("success", "").lower() == "true"]
    with Path(routes_geojson_path).open(encoding="utf-8") as handle:
        geojson = json.load(handle)
    features = geojson.get("features", [])
    selected = _select_audit_rows(rows, count=count, seed=config.random_seed)
    cases: list[dict[str, Any]] = []
    for index, row in enumerate(selected):
        case_id = f"case_{index:03d}"
        pair_id = row["pair_id"]
        pair_features = [
            feature
            for feature in features
            if str(feature.get("properties", {}).get("pair_id")) == str(pair_id)
            and str(feature.get("properties", {}).get("detour_ratio")) == str(row.get("detour_ratio"))
        ]
        case_geojson_path = config.output_dir / "audit" / f"{case_id}.geojson"
        write_json(case_geojson_path, {"type": "FeatureCollection", "features": pair_features})
        summary_path = config.output_dir / "audit" / f"{case_id}_summary.md"
        comparison = _pair_method_rows(rows, pair_id=pair_id, detour_ratio=row.get("detour_ratio", ""))
        write_markdown(summary_path, _case_summary(case_id, row, comparison))
        shortest = comparison.get("shortest_distance", {})
        proposed = comparison.get("proposed_full", {})
        cases.append(
            {
                "case_id": case_id,
                "pair_id": pair_id,
                "selection_reason": row.get("selection_reason", ""),
                "shortest_heat_dose": shortest.get("heat_dose", ""),
                "proposed_heat_dose": proposed.get("heat_dose", ""),
                "heat_dose_reduction_percent": _heat_reduction_percent(shortest, proposed),
                "shortest_distance_m": shortest.get("route_distance_m", ""),
                "proposed_distance_m": proposed.get("route_distance_m", ""),
                "detour_ratio": row.get("detour_ratio", ""),
            }
        )
    audit_csv = config.output_dir / "audit" / "audit_cases.csv"
    write_csv(audit_csv, cases, AUDIT_COLUMNS)
    return {"audit_cases": audit_csv}


def _select_audit_rows(rows: list[dict[str, str]], *, count: int, seed: int) -> list[dict[str, str]]:
    proposed = [row for row in rows if row.get("method") == "proposed_full"]
    if not proposed:
        return []
    shortest_by_pair = {
        (row.get("pair_id"), row.get("detour_ratio")): row
        for row in rows
        if row.get("method") == "shortest_distance"
    }

    def reduction(row: dict[str, str]) -> float:
        shortest = shortest_by_pair.get((row.get("pair_id"), row.get("detour_ratio")))
        if not shortest:
            return 0.0
        shortest_heat = safe_float(shortest.get("heat_dose"))
        proposed_heat = safe_float(row.get("heat_dose"))
        if shortest_heat is None or proposed_heat is None:
            return 0.0
        return shortest_heat - proposed_heat

    selections: list[dict[str, str]] = []
    for reason, row in [
        ("largest_heat_dose_reduction", max(proposed, key=reduction)),
        ("smallest_heat_dose_reduction", min(proposed, key=reduction)),
        ("largest_detour", max(proposed, key=lambda row: safe_float(row.get("excess_distance_ratio")) or 0.0)),
    ]:
        copied = dict(row)
        copied["selection_reason"] = reason
        selections.append(copied)

    hotter = [row for row in proposed if reduction(row) < 0]
    if hotter:
        copied = dict(min(hotter, key=reduction))
        copied["selection_reason"] = "optimized_route_hotter_than_shortest"
        selections.append(copied)

    shadow_rows = [row for row in rows if row.get("method") == "shadow_only"]
    shadow_by_pair = {(row.get("pair_id"), row.get("detour_ratio")): row for row in shadow_rows}
    disagreements = [
        row
        for row in proposed
        if shadow_by_pair.get((row.get("pair_id"), row.get("detour_ratio")), {}).get("edge_ids") != row.get("edge_ids")
    ]
    if disagreements:
        copied = dict(disagreements[0])
        copied["selection_reason"] = "shadow_only_and_proposed_disagree"
        selections.append(copied)

    rng = random.Random(seed)
    remaining = [row for row in proposed if row not in selections]
    rng.shuffle(remaining)
    for row in remaining:
        copied = dict(row)
        copied["selection_reason"] = "random_representative"
        selections.append(copied)
        if len(selections) >= count:
            break

    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in selections:
        key = (row.get("pair_id", ""), row.get("detour_ratio", ""), row.get("selection_reason", ""))
        if key not in seen:
            seen.add(key)
            unique.append(row)
        if len(unique) >= count:
            break
    return unique


def _pair_method_rows(rows: list[dict[str, str]], *, pair_id: str, detour_ratio: str) -> dict[str, dict[str, str]]:
    return {
        row.get("method", ""): row
        for row in rows
        if row.get("pair_id") == pair_id and row.get("detour_ratio") == detour_ratio
    }


def _case_summary(case_id: str, row: dict[str, str], comparison: dict[str, dict[str, str]]) -> str:
    shortest = comparison.get("shortest_distance", {})
    proposed = comparison.get("proposed_full", {})
    reduction = _heat_reduction_percent(shortest, proposed)
    return f"""# Audit {case_id}

This is a remote visual/plausibility audit artifact for a modeled UTCI/shadow routing benchmark. It is not field validation.

- Pair id: `{row.get("pair_id", "")}`
- Selection reason: {row.get("selection_reason", "")}
- Detour ratio: {row.get("detour_ratio", "")}
- Shortest distance (m): {shortest.get("route_distance_m", "")}
- Proposed distance (m): {proposed.get("route_distance_m", "")}
- Shortest heat dose: {shortest.get("heat_dose", "")}
- Proposed heat dose: {proposed.get("heat_dose", "")}
- Heat-dose reduction percent: {reduction if reduction is not None else ""}

Inspect the companion GeoJSON for route geometry and method properties. Any inferred explanation should be treated as a computational plausibility check only.
"""


def _heat_reduction_percent(shortest: dict[str, str], proposed: dict[str, str]) -> float | None:
    shortest_heat = safe_float(shortest.get("heat_dose"))
    proposed_heat = safe_float(proposed.get("heat_dose"))
    if shortest_heat is None or proposed_heat is None or shortest_heat == 0:
        return None
    return 100.0 * (shortest_heat - proposed_heat) / shortest_heat
