"""Common-sample routing comparisons; never infer overlap from aggregates."""

from __future__ import annotations

from itertools import combinations
import random
from statistics import fmean
from typing import Any, Sequence

from routing_backend.result_metrics import safe_float


RECORD_FIELDS = ("study_name", "config_hash", "run_id", "raster_timestamp", "pair_id", "detour_ratio")


def record_key(row: dict[str, Any]) -> tuple[str, ...]:
    values = [str(row.get(field, "")) for field in RECORD_FIELDS]
    # CSVs may serialize the same budget as 0.10 or 0.1.
    detour = safe_float(row.get("detour_ratio"))
    if detour is None:
        raise ValueError("Every route record needs a finite detour_ratio")
    values[-1] = format(detour, ".12g")
    if not row.get("pair_id"):
        raise ValueError("Every route record needs a pair_id")
    return tuple(values)


def succeeded(row: dict[str, Any]) -> bool:
    return str(row.get("success", "")).lower() in {"true", "1"}


def index_records(rows: Sequence[dict[str, Any]]) -> dict[tuple[tuple[str, ...], str], dict[str, Any]]:
    indexed = {}
    for row in rows:
        key = (record_key(row), str(row.get("method", "")))
        if key in indexed:
            raise ValueError(f"Duplicate pair-budget-method record: {key}")
        indexed[key] = row
    return indexed


def common_accepted_rows(rows: Sequence[dict[str, Any]], methods: Sequence[str]) -> list[dict[str, Any]]:
    """Keep exactly the same accepted records for all explicitly named methods.

    A successful matched shortest-distance record is always required. Missing
    methods, baseline failures and missing exposure metrics exclude a record.
    """
    required = tuple(dict.fromkeys(["shortest_distance", *methods]))
    indexed = index_records(rows)
    records = sorted({key for key, _method in indexed})
    output = []
    for key in records:
        group = [indexed.get((key, method)) for method in required]
        if all(row is not None and succeeded(row)
               and safe_float(row.get("heat_dose")) is not None for row in group):
            output.extend(dict(row) for row in group)
    return output


def paired_heat_contrasts(
    rows: Sequence[dict[str, Any]], methods: Sequence[str], *,
    bootstrap_replicates: int = 2000, seed: int = 42,
) -> list[dict[str, Any]]:
    """Compare route H on common records, resampling whole OD-pair clusters.

    Positive H_b-H_a means method a has lower mean exceedance than b. The
    intervals describe the sampled OD population within this single snapshot;
    they cannot establish transfer to other cities, hours or real pedestrians.
    """
    common = common_accepted_rows(rows, methods)
    indexed = index_records(common)
    by_budget: dict[str, set[tuple[str, ...]]] = {}
    for key, _method in indexed:
        by_budget.setdefault(key[-1], set()).add(key)
        by_budget.setdefault("all", set()).add(key)
    contrasts = []
    for budget, keys in sorted(by_budget.items()):
        for method_a, method_b in combinations(dict.fromkeys(methods), 2):
            clusters: dict[tuple[str, ...], list[float]] = {}
            for key in sorted(keys):
                value = float(indexed[(key, method_b)]["heat_dose"]) - float(indexed[(key, method_a)]["heat_dose"])
                clusters.setdefault(key[:-1], []).append(value)
            values = [value for cluster in clusters.values() for value in cluster]
            interval = _cluster_interval(list(clusters.values()), bootstrap_replicates, seed)
            contrasts.append({
                "detour_ratio": budget, "method_a": method_a, "method_b": method_b,
                "common_records": len(values), "od_clusters": len(clusters),
                "mean_H_b_minus_H_a_K": fmean(values),
                "ci95_low_K": interval[0], "ci95_high_K": interval[1],
                "bootstrap_replicates": bootstrap_replicates, "bootstrap_seed": seed,
            })
    return contrasts


def _cluster_interval(clusters: list[list[float]], replicates: int, seed: int) -> tuple[float | None, float | None]:
    if len(clusters) < 2 or replicates < 2:
        return None, None
    rng = random.Random(seed)
    samples = []
    for _ in range(replicates):
        selected = rng.choices(clusters, k=len(clusters))
        samples.append(sum(sum(values) for values in selected) / sum(len(values) for values in selected))
    samples.sort()
    return samples[int(0.025 * (replicates - 1))], samples[int(0.975 * (replicates - 1))]

