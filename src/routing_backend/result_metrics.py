"""Pure metric helpers for routing experiment outputs."""

from __future__ import annotations

import math
from statistics import fmean, median
from typing import Any, Iterable, Sequence


def safe_float(value: Any) -> float | None:
    """Return a finite float or ``None``."""

    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def percent_change(baseline: float | None, value: float | None) -> float | None:
    """Return ``100 * (value - baseline) / baseline`` with safe zero handling."""

    if baseline is None or value is None or abs(baseline) < 1e-12:
        return None
    return 100.0 * (value - baseline) / baseline


def heat_dose_reduction(shortest_heat_dose: float | None, method_heat_dose: float | None) -> float | None:
    """Absolute heat-dose reduction relative to the shortest route."""

    if shortest_heat_dose is None or method_heat_dose is None:
        return None
    return shortest_heat_dose - method_heat_dose


def heat_dose_reduction_percent(shortest_heat_dose: float | None, method_heat_dose: float | None) -> float | None:
    """Percent heat-dose reduction relative to the shortest route."""

    if shortest_heat_dose is None or method_heat_dose is None or abs(shortest_heat_dose) < 1e-12:
        return None
    return 100.0 * (shortest_heat_dose - method_heat_dose) / shortest_heat_dose


def mean_utci_reduction(shortest_mean_utci: float | None, method_mean_utci: float | None) -> float | None:
    """Mean UTCI reduction in degrees C relative to the shortest route."""

    if shortest_mean_utci is None or method_mean_utci is None:
        return None
    return shortest_mean_utci - method_mean_utci


def max_utci_reduction(shortest_max_utci: float | None, method_max_utci: float | None) -> float | None:
    """Peak UTCI reduction in degrees C relative to the shortest route."""

    if shortest_max_utci is None or method_max_utci is None:
        return None
    return shortest_max_utci - method_max_utci


def shade_fraction_increase(shortest_shade_fraction: float | None, method_shade_fraction: float | None) -> float | None:
    """Shade-fraction increase relative to the shortest route."""

    if shortest_shade_fraction is None or method_shade_fraction is None:
        return None
    return method_shade_fraction - shortest_shade_fraction


def excess_distance_ratio(route_distance_m: float | None, shortest_distance_m: float | None) -> float | None:
    """Return ``(route_distance_m - shortest_distance_m) / shortest_distance_m``."""

    if route_distance_m is None or shortest_distance_m is None or shortest_distance_m <= 0:
        return None
    return (route_distance_m - shortest_distance_m) / shortest_distance_m


def route_overlap_jaccard(route_a_edges: Iterable[Any], route_b_edges: Iterable[Any]) -> float | None:
    """Return edge-set Jaccard overlap for two routes."""

    a = {str(edge) for edge in route_a_edges}
    b = {str(edge) for edge in route_b_edges}
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return None
    return len(a & b) / len(union)


def summarize_by_group(
    rows: Iterable[dict[str, Any]],
    group_fields: Sequence[str],
    metric_fields: Sequence[str],
) -> list[dict[str, Any]]:
    """Summarize numeric metrics by one or more row fields."""

    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in group_fields)
        groups.setdefault(key, []).append(row)

    summaries: list[dict[str, Any]] = []
    for key, group_rows in sorted(groups.items()):
        summary = {field: value for field, value in zip(group_fields, key)}
        summary["count"] = len(group_rows)
        successes = [str(row.get("success", "")).lower() for row in group_rows]
        if any(value in {"true", "false", "1", "0"} for value in successes):
            success_count = sum(1 for value in successes if value in {"true", "1"})
            summary["success_rate"] = success_count / len(group_rows)
            summary["failure_rate"] = 1.0 - summary["success_rate"]
        for metric in metric_fields:
            values = [safe_float(row.get(metric)) for row in group_rows]
            clean = [value for value in values if value is not None]
            summary.update(_metric_summary(metric, clean))
        summaries.append(summary)
    return summaries


def _metric_summary(name: str, values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            f"{name}_mean": None,
            f"{name}_median": None,
            f"{name}_std": None,
            f"{name}_p10": None,
            f"{name}_p25": None,
            f"{name}_p75": None,
            f"{name}_p90": None,
        }
    values = sorted(values)
    mean = fmean(values)
    variance = fmean((value - mean) ** 2 for value in values) if len(values) > 1 else 0.0
    return {
        f"{name}_mean": mean,
        f"{name}_median": median(values),
        f"{name}_std": math.sqrt(variance),
        f"{name}_p10": _quantile(values, 0.10),
        f"{name}_p25": _quantile(values, 0.25),
        f"{name}_p75": _quantile(values, 0.75),
        f"{name}_p90": _quantile(values, 0.90),
    }


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        raise ValueError("values must be non-empty")
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction
