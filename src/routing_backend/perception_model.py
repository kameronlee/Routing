"""Development fallback perception models and slope helpers."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import math
from typing import Any


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _first(value: Any) -> Any:
    if isinstance(value, (list, tuple, set)):
        return next(iter(value), None)
    return value


def _stable_unit_interval(payload: str) -> float:
    digest = sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def compute_scenic_score(edge: Mapping[str, Any]) -> float:
    """Estimate segment scenicness on a 0-1 scale for explicit fallback mode."""

    highway = str(_first(edge.get("highway", ""))).lower()
    landuse = str(_first(edge.get("landuse", ""))).lower()
    natural = str(_first(edge.get("natural", ""))).lower()

    base = 0.42
    if highway in {"footway", "path", "pedestrian", "cycleway", "living_street"}:
        base += 0.18
    if highway in {"primary", "secondary", "tertiary", "trunk", "motorway"}:
        base -= 0.16
    if landuse in {"forest", "grass", "meadow", "park", "recreation_ground"}:
        base += 0.24
    if natural in {"tree", "wood", "scrub", "grassland", "water"}:
        base += 0.22

    canopy = edge.get("tree_canopy_fraction", edge.get("greenery_index"))
    if canopy is not None:
        base = 0.55 * base + 0.45 * _clamp(float(canopy))
    else:
        jitter_payload = f"{edge.get('osmid', '')}|{edge.get('name', '')}|{edge.get('length', '')}"
        base += (_stable_unit_interval(jitter_payload) - 0.5) * 0.12

    return _clamp(base)


def compute_noise_score(edge: Mapping[str, Any]) -> float:
    """Estimate traffic-related noise exposure for explicit fallback mode.

    A value near 0 is quiet and a value near 1 is noisy.
    """

    highway = str(_first(edge.get("highway", "residential"))).lower()
    road_noise = {
        "motorway": 0.96,
        "trunk": 0.90,
        "primary": 0.78,
        "secondary": 0.64,
        "tertiary": 0.52,
        "unclassified": 0.40,
        "residential": 0.32,
        "living_street": 0.22,
        "service": 0.24,
        "cycleway": 0.14,
        "footway": 0.08,
        "path": 0.08,
        "pedestrian": 0.10,
        "steps": 0.06,
    }.get(highway, 0.38)

    lanes = edge.get("lanes")
    if lanes is not None:
        try:
            road_noise += max(0.0, float(_first(lanes)) - 1.0) * 0.05
        except (TypeError, ValueError):
            pass

    for attribute, weight in (
        ("gps_trajectory_intensity", 0.15),
        ("socioeconomic_noise_index", 0.12),
        ("truck_route_fraction", 0.18),
    ):
        if attribute in edge:
            road_noise += _clamp(float(edge[attribute])) * weight

    return _clamp(road_noise)


def compute_slope(
    edge: Mapping[str, Any],
    length_m: float,
    elevation_start_m: float | None = None,
    elevation_end_m: float | None = None,
) -> tuple[float, float]:
    """Return signed slope ratio and elevation change in metres."""

    if length_m <= 0:
        return 0.0, 0.0

    if "elevation_change_m" in edge:
        elevation_change_m = float(edge["elevation_change_m"])
    elif elevation_start_m is not None and elevation_end_m is not None:
        elevation_change_m = elevation_end_m - elevation_start_m
    else:
        elevation_change_m = 0.0

    slope = elevation_change_m / length_m
    if not math.isfinite(slope):
        slope = 0.0
    return slope, elevation_change_m
