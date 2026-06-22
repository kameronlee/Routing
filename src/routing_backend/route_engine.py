"""Feature extraction, utility scoring and constrained path search."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import heapq
import itertools
import math
from pathlib import Path
from statistics import fmean
import time
from typing import Any, Hashable, Iterable, MutableMapping, Sequence

import networkx as nx

try:
    from shapely import wkt
except ImportError:  # pragma: no cover - optional OSM GraphML geometry support
    wkt = None  # type: ignore[assignment]

from routing_backend.microclimate_model import (
    Coordinate,
    densify_geometry,
    haversine_distance_m,
    sample_microclimate_along_geometry,
    solar_position,
    summarize_utci_samples,
)
from routing_backend.perception_model import (
    compute_noise_score,
    compute_scenic_score,
    compute_slope,
)
from routing_backend.preferences import Preference


@dataclass(frozen=True)
class EdgeFeatures:
    """Feature vector ``z_e(t)`` for an edge at a departure time."""

    length_m: float
    travel_time_s: float
    mean_utci: float
    max_utci: float
    heat_dose: float
    shade_fraction: float
    scenic_score: float
    noise_score: float
    slope: float
    elevation_change_m: float
    poi_density: float = 0.0
    uncertainty: float = 0.0


@dataclass(frozen=True)
class EdgeTraversal:
    """Concrete directed edge selected by the routing algorithm."""

    u: Hashable
    v: Hashable
    key: Hashable | None = None


@dataclass(frozen=True)
class RouteCandidate:
    """A routed path and its aggregated comfort/perception statistics."""

    geometry: list[Coordinate]
    edge_ids: list[str]
    distance_m: float
    duration_s: float
    mean_utci: float
    max_utci: float
    heat_dose: float
    shade_fraction: float
    scenic_score: float
    noise_score: float
    slope_penalty: float
    cost: float


def _mode_speed_mps(mode: str) -> float:
    return 4.5 if mode in {"bike", "cycle", "cycling"} else 1.35


def _edge_length_from_geometry(points: Sequence[Coordinate]) -> float:
    return sum(haversine_distance_m(a, b) for a, b in zip(points, points[1:]))


def _direct_shade_fraction(shadow_values: Sequence[float]) -> float | None:
    """Return fraction of SOLWEIG shadow samples in shade.

    SOLWEIG-GPU stores direct shadow as 0=shadow and 1=sunlit.
    """

    if not shadow_values:
        return None
    return sum(1 for value in shadow_values if value <= 0.5) / len(shadow_values)


def _clamp_fraction(value: float) -> float:
    return max(0.0, min(1.0, value))


def _first_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return _first_number(value[0]) if value else None
    if isinstance(value, str):
        text = value.strip().lower()
        for separator in (";", ","):
            text = text.split(separator, 1)[0]
        text = text.replace("meters", "").replace("meter", "").replace("m", "").strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
    return number if number > 0.0 else None


def _street_width_m(data: dict[str, Any]) -> float:
    width = (
        _first_number(data.get("street_width_m"))
        or _first_number(data.get("street_width"))
        or _first_number(data.get("width"))
    )
    if width is not None:
        return width
    lanes = _first_number(data.get("lanes"))
    if lanes is not None:
        return max(4.0, lanes * 3.2)
    return 10.0


def _edge_bearing_degrees(points: Sequence[Coordinate]) -> float | None:
    if len(points) < 2:
        return None

    start = points[0]
    end = points[-1]
    if haversine_distance_m(start, end) < 0.1:
        return None

    lat1, lon1 = map(math.radians, start)
    lat2, lon2 = map(math.radians, end)
    delta_lon = lon2 - lon1
    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _geometry_midpoint(points: Sequence[Coordinate]) -> Coordinate:
    if not points:
        return 0.0, 0.0
    midpoint = points[len(points) // 2]
    return float(midpoint[0]), float(midpoint[1])


def _azimuth_shade_fraction(
    points: Sequence[Coordinate],
    data: dict[str, Any],
    departure_time: datetime | float | int | None,
) -> float | None:
    """Estimate shade from sun azimuth, edge bearing and real height attributes."""

    bearing = _edge_bearing_degrees(points)
    if bearing is None:
        return None

    canopy_fraction = _clamp_fraction(
        _first_number(data.get("tree_canopy_fraction"))
        or _first_number(data.get("landcover_green_fraction"))
        or _first_number(data.get("greenery_index"))
        or 0.0
    )
    canopy_height_m = max(
        _first_number(data.get("canopy_height_mean_m")) or 0.0,
        (_first_number(data.get("canopy_height_max_m")) or 0.0) * 0.5,
    )
    building_height_m = max(
        _first_number(data.get("building_height_mean_m")) or 0.0,
        (_first_number(data.get("building_height_max_m")) or 0.0) * 0.6,
    )
    if canopy_fraction <= 0.0 and canopy_height_m <= 0.0 and building_height_m <= 0.0:
        return None

    sun = solar_position(_geometry_midpoint(points), departure_time)
    if sun.altitude_deg <= 0.0:
        return 1.0

    street_width_m = _street_width_m(data)
    alignment = abs(math.sin(math.radians(sun.azimuth_deg - bearing)))
    tan_altitude = max(math.tan(math.radians(sun.altitude_deg)), 1e-6)

    def cast_fraction(height_m: float) -> float:
        if height_m <= 0.0:
            return 0.0
        shadow_length_m = height_m / tan_altitude
        return _clamp_fraction((shadow_length_m * alignment) / street_width_m)

    building_cast = cast_fraction(building_height_m)
    canopy_cast = cast_fraction(canopy_height_m) * canopy_fraction
    return _clamp_fraction(max(canopy_fraction, building_cast, canopy_cast))


def edge_geometry_points(graph: nx.Graph, u: Hashable, v: Hashable, data: dict[str, Any]) -> list[Coordinate]:
    """Return edge geometry as ``(lat, lon)`` points."""

    if "geometry_points" in data:
        return [(float(lat), float(lon)) for lat, lon in data["geometry_points"]]

    geometry = data.get("geometry")
    if wkt is not None and isinstance(geometry, str) and geometry.strip().upper().startswith("LINESTRING"):
        try:
            geometry = wkt.loads(geometry)
        except Exception:
            geometry = None
    if geometry is not None and hasattr(geometry, "coords"):
        return [(float(y), float(x)) for x, y in geometry.coords]

    u_data = graph.nodes[u]
    v_data = graph.nodes[v]
    return [
        (float(u_data["y"]), float(u_data["x"])),
        (float(v_data["y"]), float(v_data["x"])),
    ]


def build_edge_features(
    graph: nx.Graph,
    u: Hashable,
    v: Hashable,
    data: dict[str, Any],
    departure_time: datetime | float | int | None,
    mode: str = "walk",
    sample_spacing_m: float = 20.0,
    comfort_threshold: float = 26.0,
    utci_raster_path: str | Path | None = None,
    real_feature_context: Any | None = None,
) -> EdgeFeatures:
    """Compute the radiative-perceptual feature vector for one edge."""

    points = edge_geometry_points(graph, u, v, data)
    length_m = float(data.get("length") or _edge_length_from_geometry(points))
    if real_feature_context is not None:
        data.update(real_feature_context.edge_attributes(points, data, length_m))
    travel_time_s = float(data.get("travel_time") or length_m / _mode_speed_mps(mode))
    dense_points = None
    if real_feature_context is not None and hasattr(real_feature_context, "utci_values"):
        dense_points = densify_geometry(points, spacing_m=sample_spacing_m)
        values = real_feature_context.utci_values(dense_points)
        if not values:
            raise ValueError(f"No valid UTCI samples found in raster {utci_raster_path}")
        climate = summarize_utci_samples(
            values,
            departure_time=departure_time,
            comfort_threshold=comfort_threshold,
        )
    else:
        climate = sample_microclimate_along_geometry(
            points,
            departure_time=departure_time,
            spacing_m=sample_spacing_m,
            comfort_threshold=comfort_threshold,
            raster_path=utci_raster_path,
        )
    shade_fraction = climate.shade_fraction
    if real_feature_context is not None and hasattr(real_feature_context, "shadow_values"):
        if dense_points is None:
            dense_points = densify_geometry(points, spacing_m=sample_spacing_m)
        direct_shade_fraction = _direct_shade_fraction(real_feature_context.shadow_values(dense_points))
        if direct_shade_fraction is not None:
            shade_fraction = direct_shade_fraction
        else:
            azimuth_shade_fraction = _azimuth_shade_fraction(points, data, departure_time)
            if azimuth_shade_fraction is not None:
                shade_fraction = max(shade_fraction, azimuth_shade_fraction)
    else:
        azimuth_shade_fraction = _azimuth_shade_fraction(points, data, departure_time)
        if azimuth_shade_fraction is not None:
            shade_fraction = max(shade_fraction, azimuth_shade_fraction)
    u_elevation = graph.nodes[u].get("elevation")
    v_elevation = graph.nodes[v].get("elevation")
    slope, elevation_change_m = compute_slope(
        data,
        length_m=length_m,
        elevation_start_m=float(u_elevation) if u_elevation is not None else None,
        elevation_end_m=float(v_elevation) if v_elevation is not None else None,
    )

    return EdgeFeatures(
        length_m=length_m,
        travel_time_s=travel_time_s,
        mean_utci=climate.mean_utci,
        max_utci=climate.max_utci,
        heat_dose=climate.heat_dose,
        shade_fraction=shade_fraction,
        scenic_score=float(data.get("scenic_score", compute_scenic_score(data))),
        noise_score=float(data.get("noise_score", compute_noise_score(data))),
        slope=slope,
        elevation_change_m=elevation_change_m,
        poi_density=float(data.get("poi_density", 0.0)),
        uncertainty=float(data.get("feature_uncertainty", 0.15 if data.get("source") == "synthetic" else 0.05)),
    )


def _edge_records(
    graph: nx.Graph,
) -> list[tuple[Hashable, Hashable, Hashable | None, dict[str, Any]]]:
    if graph.is_multigraph():
        return [(u, v, key, data) for u, v, key, data in graph.edges(keys=True, data=True)]
    return [(u, v, None, data) for u, v, data in graph.edges(data=True)]


def _assign_batched_real_features(
    graph: nx.MultiDiGraph,
    departure_time: datetime | float | int | None,
    mode: str,
    sample_spacing_m: float,
    comfort_threshold: float,
    utci_raster_path: str | Path | None,
    real_feature_context: Any,
    feature_cache: MutableMapping[tuple[Any, ...], EdgeFeatures] | None = None,
) -> list[EdgeTraversal]:
    records = _edge_records(graph)
    point_groups: list[list[Coordinate]] = []
    context_groups: list[tuple[Sequence[Coordinate], dict[str, Any], float]] = []
    lengths: list[float] = []
    pending_records: list[tuple[Hashable, Hashable, Hashable | None, dict[str, Any]]] = []
    pending_cache_keys: list[tuple[Any, ...] | None] = []

    for u, v, _key, data in records:
        cache_key = _edge_feature_cache_key(
            real_feature_context,
            utci_raster_path=utci_raster_path,
            departure_time=departure_time,
            mode=mode,
            sample_spacing_m=sample_spacing_m,
            comfort_threshold=comfort_threshold,
            u=u,
            v=v,
            key=_key,
        )
        cached_features = feature_cache.get(cache_key) if feature_cache is not None else None
        if cached_features is not None:
            data["features"] = cached_features
            data["length"] = cached_features.length_m
            data["travel_time"] = cached_features.travel_time_s
            continue

        points = edge_geometry_points(graph, u, v, data)
        length_m = float(data.get("length") or _edge_length_from_geometry(points))
        pending_records.append((u, v, _key, data))
        pending_cache_keys.append(cache_key)
        point_groups.append(densify_geometry(points, spacing_m=sample_spacing_m))
        context_groups.append((points, data, length_m))
        lengths.append(length_m)

    if not pending_records:
        return []

    try:
        attribute_groups = real_feature_context.edge_attributes_many(
            context_groups,
            sample_spacing_m=min(sample_spacing_m, 20.0),
        )
    except TypeError:
        attribute_groups = real_feature_context.edge_attributes_many(context_groups)
    utci_groups = real_feature_context.utci_values_many(point_groups)
    if hasattr(real_feature_context, "shadow_values_many"):
        shadow_groups = real_feature_context.shadow_values_many(point_groups)
    else:
        shadow_groups = [[] for _record in pending_records]
    missing_utci_edges: list[EdgeTraversal] = []

    for (
        (u, v, key, data),
        cache_key,
        (points, _edge_data, _length_m),
        length_m,
        attributes,
        utci_values,
        shadow_values,
    ) in zip(
        pending_records,
        pending_cache_keys,
        context_groups,
        lengths,
        attribute_groups,
        utci_groups,
        shadow_groups,
    ):
        if not utci_values:
            missing_utci_edges.append(EdgeTraversal(u, v, key))
            continue

        data.update(attributes)
        travel_time_s = float(data.get("travel_time") or length_m / _mode_speed_mps(mode))
        climate = summarize_utci_samples(
            utci_values,
            departure_time=departure_time,
            comfort_threshold=comfort_threshold,
        )
        shade_fraction = _direct_shade_fraction(shadow_values)
        if shade_fraction is None:
            shade_fraction = climate.shade_fraction
            azimuth_shade_fraction = _azimuth_shade_fraction(points, data, departure_time)
            if azimuth_shade_fraction is not None:
                shade_fraction = max(shade_fraction, azimuth_shade_fraction)
        u_elevation = graph.nodes[u].get("elevation")
        v_elevation = graph.nodes[v].get("elevation")
        slope, elevation_change_m = compute_slope(
            data,
            length_m=length_m,
            elevation_start_m=float(u_elevation) if u_elevation is not None else None,
            elevation_end_m=float(v_elevation) if v_elevation is not None else None,
        )
        features = EdgeFeatures(
            length_m=length_m,
            travel_time_s=travel_time_s,
            mean_utci=climate.mean_utci,
            max_utci=climate.max_utci,
            heat_dose=climate.heat_dose,
            shade_fraction=shade_fraction,
            scenic_score=float(data.get("scenic_score", compute_scenic_score(data))),
            noise_score=float(data.get("noise_score", compute_noise_score(data))),
            slope=slope,
            elevation_change_m=elevation_change_m,
            poi_density=float(data.get("poi_density", 0.0)),
            uncertainty=float(data.get("feature_uncertainty", 0.15 if data.get("source") == "synthetic" else 0.05)),
        )
        data["features"] = features
        data["length"] = features.length_m
        data["travel_time"] = features.travel_time_s
        if feature_cache is not None and cache_key is not None:
            feature_cache[cache_key] = features

    return missing_utci_edges


def _edge_feature_cache_key(
    real_feature_context: Any,
    *,
    utci_raster_path: str | Path | None,
    departure_time: datetime | float | int | None,
    mode: str,
    sample_spacing_m: float,
    comfort_threshold: float,
    u: Hashable,
    v: Hashable,
    key: Hashable | None,
) -> tuple[Any, ...]:
    paths = getattr(real_feature_context, "paths", None)
    if paths is None:
        path_key: tuple[str, ...] = (str(utci_raster_path),)
    else:
        path_key = tuple(
            str(path)
            for path in (
                paths.utci_raster,
                paths.shadow_raster,
                *paths.canopy_height_rasters,
                *paths.canopy_class_rasters,
                *paths.landcover_rasters,
                paths.traffic_geojson,
                *getattr(paths, "building_height_rasters", ()),
            )
            if path is not None
        )
    return (
        path_key,
        mode,
        departure_time.isoformat() if isinstance(departure_time, datetime) else departure_time,
        round(sample_spacing_m, 3),
        round(comfort_threshold, 3),
        u,
        v,
        key,
    )


def build_feature_graph(
    graph: nx.MultiDiGraph,
    departure_time: datetime | float | int | None,
    mode: str = "walk",
    sample_spacing_m: float = 20.0,
    comfort_threshold: float = 26.0,
    utci_raster_path: str | Path | None = None,
    real_feature_context: Any | None = None,
    feature_cache: MutableMapping[tuple[Any, ...], EdgeFeatures] | None = None,
) -> nx.MultiDiGraph:
    """Return a graph copy whose edges contain ``EdgeFeatures`` objects."""

    feature_graph = graph.copy()
    missing_utci_edges: list[EdgeTraversal] = []
    if (
        real_feature_context is not None
        and hasattr(real_feature_context, "edge_attributes_many")
        and hasattr(real_feature_context, "utci_values_many")
    ):
        missing_utci_edges = _assign_batched_real_features(
            feature_graph,
            departure_time=departure_time,
            mode=mode,
            sample_spacing_m=sample_spacing_m,
            comfort_threshold=comfort_threshold,
            utci_raster_path=utci_raster_path,
            real_feature_context=real_feature_context,
            feature_cache=feature_cache,
        )
    elif feature_graph.is_multigraph():
        edge_iter = list(feature_graph.edges(keys=True, data=True))
        for u, v, _key, data in edge_iter:
            try:
                features = build_edge_features(
                    feature_graph,
                    u,
                    v,
                    data,
                    departure_time=departure_time,
                    mode=mode,
                    sample_spacing_m=sample_spacing_m,
                    comfort_threshold=comfort_threshold,
                    utci_raster_path=utci_raster_path,
                    real_feature_context=real_feature_context,
                )
            except ValueError as exc:
                if utci_raster_path is not None and "No valid UTCI samples found in raster" in str(exc):
                    missing_utci_edges.append(EdgeTraversal(u, v, _key))
                    continue
                raise
            data["features"] = features
            data["length"] = features.length_m
            data["travel_time"] = features.travel_time_s
    else:
        for u, v, data in list(feature_graph.edges(data=True)):
            try:
                features = build_edge_features(
                    feature_graph,
                    u,
                    v,
                    data,
                    departure_time=departure_time,
                    mode=mode,
                    sample_spacing_m=sample_spacing_m,
                    comfort_threshold=comfort_threshold,
                    utci_raster_path=utci_raster_path,
                    real_feature_context=real_feature_context,
                )
            except ValueError as exc:
                if utci_raster_path is not None and "No valid UTCI samples found in raster" in str(exc):
                    missing_utci_edges.append(EdgeTraversal(u, v))
                    continue
                raise
            data["features"] = features
            data["length"] = features.length_m
            data["travel_time"] = features.travel_time_s
    for edge in missing_utci_edges:
        if feature_graph.is_multigraph():
            feature_graph.remove_edge(edge.u, edge.v, edge.key)
        else:
            feature_graph.remove_edge(edge.u, edge.v)
    if missing_utci_edges:
        feature_graph.graph["removed_no_utci_edges"] = len(missing_utci_edges)
    if feature_graph.number_of_edges() == 0:
        raise ValueError(f"No route graph edges have valid UTCI coverage in raster {utci_raster_path}")
    return feature_graph


def cost(features: EdgeFeatures, pref: Preference) -> float:
    """Convert an edge feature vector and user preference into scalar cost."""

    cool_penalty = (
        max(0.0, features.mean_utci - pref.comfort_threshold) / 8.0
        + max(0.0, features.max_utci - pref.comfort_threshold) / 10.0
        + features.heat_dose / 6.0
        + (1.0 - features.shade_fraction) * 0.45
    )
    scenic_penalty = (1.0 - features.scenic_score) ** 2
    noise_penalty = features.noise_score**2
    slope_penalty = abs(features.slope) * 10.0 + max(0.0, features.elevation_change_m) / 25.0
    exposure_units = max(features.length_m, 1.0) / 100.0

    scalar = (
        pref.weight_distance * (features.length_m / 1_000.0)
        + pref.weight_time * (features.travel_time_s / 600.0)
        + exposure_units
        * (
            pref.weight_cool * cool_penalty
            + pref.weight_scenic * scenic_penalty
            + pref.weight_quiet * noise_penalty
            + pref.weight_slope * slope_penalty
            + pref.uncertainty_penalty * features.uncertainty
        )
    )
    return max(0.0, scalar)


def _out_edges(graph: nx.Graph, node: Hashable) -> Iterable[tuple[Hashable, Hashable, Hashable | None, dict[str, Any]]]:
    if graph.is_multigraph():
        yield from graph.out_edges(node, keys=True, data=True)  # type: ignore[attr-defined]
    else:
        for u, v, data in graph.out_edges(node, data=True):  # type: ignore[attr-defined]
            yield u, v, None, data


def _edge_features(data: dict[str, Any]) -> EdgeFeatures:
    features = data.get("features")
    if isinstance(features, EdgeFeatures):
        return features
    return EdgeFeatures(
        length_m=float(data.get("length", 1.0)),
        travel_time_s=float(data.get("travel_time", data.get("length", 1.0))),
        mean_utci=float(data.get("mean_utci", 26.0)),
        max_utci=float(data.get("max_utci", 26.0)),
        heat_dose=float(data.get("heat_dose", 0.0)),
        shade_fraction=float(data.get("shade_fraction", 0.0)),
        scenic_score=float(data.get("scenic_score", 0.5)),
        noise_score=float(data.get("noise_score", 0.5)),
        slope=float(data.get("slope", 0.0)),
        elevation_change_m=float(data.get("elevation_change_m", 0.0)),
        poi_density=float(data.get("poi_density", 0.0)),
        uncertainty=float(data.get("uncertainty", 0.0)),
    )


def _edge_data_options(data: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield concrete edge attribute dictionaries from NetworkX weight data."""

    if "features" in data or "length" in data:
        yield data
        return
    options = [value for value in data.values() if isinstance(value, dict)]
    if options:
        yield from options
    else:
        yield data


def _minimum_edge_cost(data: dict[str, Any], preference: Preference) -> float:
    return min(cost(_edge_features(edge_data), preference) for edge_data in _edge_data_options(data))


def baseline_shortest_path_distance(
    graph: nx.Graph,
    origin_node: Hashable,
    destination_node: Hashable,
) -> float:
    """Return length of the baseline shortest path in metres."""

    return float(nx.shortest_path_length(graph, origin_node, destination_node, weight="length"))


def _is_dominated(labels: Sequence[tuple[float, float]], length_m: float, path_cost: float) -> bool:
    return any(
        existing_length <= length_m + 1e-9 and existing_cost <= path_cost + 1e-9
        for existing_length, existing_cost in labels
    )


def _pruned_labels(
    labels: Sequence[tuple[float, float]],
    length_m: float,
    path_cost: float,
    max_labels: int,
) -> list[tuple[float, float]]:
    kept = [
        (existing_length, existing_cost)
        for existing_length, existing_cost in labels
        if not (length_m <= existing_length and path_cost <= existing_cost)
    ]
    kept.append((length_m, path_cost))
    kept.sort(key=lambda label: (label[1], label[0]))
    return kept[:max_labels]


def _cost_shortest_candidate_within_budget(
    graph: nx.MultiDiGraph,
    origin_node: Hashable,
    destination_node: Hashable,
    preference: Preference,
    maximum_distance: float,
    departure_time: datetime | float | int | None,
    utci_raster_path: str | Path | None,
) -> RouteCandidate | None:
    """Return the unconstrained best-cost route when it already fits the budget."""

    try:
        path_nodes = nx.shortest_path(
            graph,
            origin_node,
            destination_node,
            weight=lambda _u, _v, data: _minimum_edge_cost(data, preference),
        )
    except nx.NetworkXNoPath:
        return None

    traversals = [_best_edge_between(graph, u, v, preference) for u, v in zip(path_nodes, path_nodes[1:])]
    route_length = sum(_edge_features(_data_for_traversal(graph, traversal)).length_m for traversal in traversals)
    if route_length > maximum_distance + 1e-9:
        return None
    return summarize_route(
        graph,
        traversals,
        preference,
        departure_time=departure_time,
        utci_raster_path=utci_raster_path,
    )


def resource_constrained_routes(
    graph: nx.MultiDiGraph,
    origin_node: Hashable,
    destination_node: Hashable,
    preference: Preference,
    delta: float = 0.20,
    max_candidates: int = 3,
    max_labels_per_node: int = 8,
    max_search_seconds: float = 1.5,
    max_expansions: int = 20_000,
    departure_time: datetime | float | int | None = None,
    utci_raster_path: str | Path | None = None,
) -> list[RouteCandidate]:
    """Find low-cost routes subject to a detour budget.

    The algorithm is a label-setting bi-objective Dijkstra search. Each label
    tracks both accumulated route utility cost and accumulated distance, while
    dominated labels are pruned at every node.
    """

    if delta < 0:
        raise ValueError("delta must be non-negative")
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1")

    if origin_node == destination_node:
        node_data = graph.nodes[origin_node]
        point = (float(node_data["y"]), float(node_data["x"]))
        return [
            RouteCandidate(
                geometry=[point],
                edge_ids=[],
                distance_m=0.0,
                duration_s=0.0,
                mean_utci=0.0,
                max_utci=0.0,
                heat_dose=0.0,
                shade_fraction=1.0,
                scenic_score=1.0,
                noise_score=0.0,
                slope_penalty=0.0,
                cost=0.0,
            )
        ]

    baseline_distance = baseline_shortest_path_distance(graph, origin_node, destination_node)
    maximum_distance = baseline_distance * (1.0 + delta)
    fast_candidate = _cost_shortest_candidate_within_budget(
        graph,
        origin_node,
        destination_node,
        preference,
        maximum_distance,
        departure_time,
        utci_raster_path,
    )
    if max_candidates == 1 and fast_candidate is not None:
        return [fast_candidate]

    try:
        distance_to_destination = nx.single_source_dijkstra_path_length(
            graph.reverse(copy=False),
            destination_node,
            cutoff=maximum_distance,
            weight="length",
        )
    except nx.NetworkXError:
        distance_to_destination = {}

    counter = itertools.count()
    queue: list[
        tuple[
            float,
            int,
            Hashable,
            float,
            list[Hashable],
            list[EdgeTraversal],
        ]
    ] = [(0.0, next(counter), origin_node, 0.0, [origin_node], [])]
    labels: dict[Hashable, list[tuple[float, float]]] = {origin_node: [(0.0, 0.0)]}
    candidates: list[RouteCandidate] = [fast_candidate] if fast_candidate is not None else []
    seen_edge_sequences: set[tuple[str, ...]] = {
        tuple(fast_candidate.edge_ids)
    } if fast_candidate is not None else set()
    search_started = time.monotonic()
    expansions = 0
    search_truncated = False

    while queue and len(candidates) < max_candidates:
        if expansions >= max_expansions or time.monotonic() - search_started >= max_search_seconds:
            search_truncated = True
            break
        expansions += 1
        path_cost, _order, node, length_m, path_nodes, path_edges = heapq.heappop(queue)

        if node == destination_node:
            candidate = summarize_route(
                graph,
                path_edges,
                preference,
                path_cost=path_cost,
                departure_time=departure_time,
                utci_raster_path=utci_raster_path,
            )
            signature = tuple(candidate.edge_ids)
            if signature not in seen_edge_sequences:
                seen_edge_sequences.add(signature)
                candidates.append(candidate)
            continue

        for u, v, key, data in _out_edges(graph, node):
            if v in path_nodes:
                continue
            features = _edge_features(data)
            next_length = length_m + features.length_m
            if next_length > maximum_distance + 1e-9:
                continue
            remaining_distance = distance_to_destination.get(v)
            if remaining_distance is None or next_length + remaining_distance > maximum_distance + 1e-9:
                continue
            edge_cost = cost(features, preference)
            next_cost = path_cost + edge_cost
            node_labels = labels.get(v, [])
            if _is_dominated(node_labels, next_length, next_cost):
                continue

            labels[v] = _pruned_labels(node_labels, next_length, next_cost, max_labels_per_node)
            heapq.heappush(
                queue,
                (
                    next_cost,
                    next(counter),
                    v,
                    next_length,
                    [*path_nodes, v],
                    [*path_edges, EdgeTraversal(u=u, v=v, key=key)],
                ),
            )

    graph.graph["route_search_expansions"] = expansions
    graph.graph["route_search_truncated"] = search_truncated

    if not candidates:
        candidates.append(
            shortest_path_candidate(
                graph,
                origin_node,
                destination_node,
                preference,
                departure_time=departure_time,
                utci_raster_path=utci_raster_path,
            )
        )

    return candidates


def _data_for_traversal(graph: nx.Graph, traversal: EdgeTraversal) -> dict[str, Any]:
    if graph.is_multigraph():
        return graph.edges[traversal.u, traversal.v, traversal.key]
    return graph.edges[traversal.u, traversal.v]


def _best_edge_between(graph: nx.Graph, u: Hashable, v: Hashable, preference: Preference) -> EdgeTraversal:
    if graph.is_multigraph():
        edge_options = graph.get_edge_data(u, v)
        if not edge_options:
            raise nx.NetworkXNoPath(f"No edge between {u!r} and {v!r}")
        best_key = min(
            edge_options,
            key=lambda key: cost(_edge_features(edge_options[key]), preference),
        )
        return EdgeTraversal(u=u, v=v, key=best_key)
    return EdgeTraversal(u=u, v=v, key=None)


def _shortest_edge_between(graph: nx.Graph, u: Hashable, v: Hashable) -> EdgeTraversal:
    if graph.is_multigraph():
        edge_options = graph.get_edge_data(u, v)
        if not edge_options:
            raise nx.NetworkXNoPath(f"No edge between {u!r} and {v!r}")
        best_key = min(edge_options, key=lambda key: float(edge_options[key].get("length", 1.0)))
        return EdgeTraversal(u=u, v=v, key=best_key)
    return EdgeTraversal(u=u, v=v, key=None)


def _combine_geometries(graph: nx.Graph, traversals: Sequence[EdgeTraversal]) -> list[Coordinate]:
    geometry: list[Coordinate] = []
    for traversal in traversals:
        data = _data_for_traversal(graph, traversal)
        edge_points = edge_geometry_points(graph, traversal.u, traversal.v, data)
        if geometry and edge_points and geometry[-1] == edge_points[0]:
            geometry.extend(edge_points[1:])
        else:
            geometry.extend(edge_points)
    return geometry


def summarize_route(
    graph: nx.Graph,
    traversals: Sequence[EdgeTraversal],
    preference: Preference,
    path_cost: float | None = None,
    departure_time: datetime | float | int | None = None,
    utci_raster_path: str | Path | None = None,
) -> RouteCandidate:
    """Aggregate edge and sampled raster statistics for a route."""

    if not traversals:
        raise ValueError("Route must contain at least one edge")

    features = [_edge_features(_data_for_traversal(graph, traversal)) for traversal in traversals]
    distance_m = sum(feature.length_m for feature in features)
    duration_s = sum(feature.travel_time_s for feature in features)
    weights = [max(feature.length_m, 1e-9) for feature in features]
    geometry = _combine_geometries(graph, traversals)

    total_weight = sum(weights)
    mean_utci = sum(feature.mean_utci * weight for feature, weight in zip(features, weights)) / total_weight
    max_utci = max(feature.max_utci for feature in features)
    heat_dose = sum(feature.heat_dose * weight for feature, weight in zip(features, weights)) / total_weight
    shade_fraction = sum(feature.shade_fraction * weight for feature, weight in zip(features, weights)) / total_weight
    scenic_score = sum(feature.scenic_score * weight for feature, weight in zip(features, weights)) / total_weight
    noise_score = sum(feature.noise_score * weight for feature, weight in zip(features, weights)) / total_weight
    slope_penalty = sum(
        (abs(feature.slope) + max(0.0, feature.elevation_change_m) / max(feature.length_m, 1.0)) * weight
        for feature, weight in zip(features, weights)
    ) / total_weight
    scalar_cost = path_cost if path_cost is not None else sum(cost(feature, preference) for feature in features)

    return RouteCandidate(
        geometry=geometry,
        edge_ids=[
            f"{traversal.u}->{traversal.v}" if traversal.key is None else f"{traversal.u}->{traversal.v}:{traversal.key}"
            for traversal in traversals
        ],
        distance_m=distance_m,
        duration_s=duration_s,
        mean_utci=mean_utci,
        max_utci=max_utci,
        heat_dose=heat_dose,
        shade_fraction=shade_fraction,
        scenic_score=scenic_score,
        noise_score=noise_score,
        slope_penalty=slope_penalty,
        cost=scalar_cost,
    )


def shortest_path_candidate(
    graph: nx.MultiDiGraph,
    origin_node: Hashable,
    destination_node: Hashable,
    preference: Preference,
    departure_time: datetime | float | int | None = None,
    utci_raster_path: str | Path | None = None,
) -> RouteCandidate:
    """Build a route candidate from the baseline length-shortest path."""

    path_nodes = nx.shortest_path(graph, origin_node, destination_node, weight="length")
    traversals = [
        _best_edge_between(graph, u, v, preference)
        for u, v in zip(path_nodes, path_nodes[1:])
    ]
    return summarize_route(
        graph,
        traversals,
        preference=preference,
        departure_time=departure_time,
        utci_raster_path=utci_raster_path,
    )


def node_path_candidate(
    graph: nx.MultiDiGraph,
    path_nodes: Sequence[Hashable],
    preference: Preference,
    departure_time: datetime | float | int | None = None,
    utci_raster_path: str | Path | None = None,
) -> RouteCandidate:
    """Score a preselected node path using its best parallel edge choices."""

    if len(path_nodes) < 2:
        raise ValueError("A candidate node path must contain at least two nodes")
    traversals = [
        _best_edge_between(graph, u, v, preference)
        for u, v in zip(path_nodes, path_nodes[1:])
    ]
    return summarize_route(
        graph,
        traversals,
        preference=preference,
        departure_time=departure_time,
        utci_raster_path=utci_raster_path,
    )


def length_shortest_route_candidate(
    graph: nx.MultiDiGraph,
    origin_node: Hashable,
    destination_node: Hashable,
    preference: Preference,
    departure_time: datetime | float | int | None = None,
    mode: str = "walk",
    sample_spacing_m: float = 20.0,
    comfort_threshold: float = 26.0,
    utci_raster_path: str | Path | None = None,
    real_feature_context: Any | None = None,
) -> RouteCandidate:
    """Build the true length-shortest route and score only its selected edges."""

    path_nodes = nx.shortest_path(graph, origin_node, destination_node, weight="length")
    traversals = [_shortest_edge_between(graph, u, v) for u, v in zip(path_nodes, path_nodes[1:])]
    for traversal in traversals:
        data = _data_for_traversal(graph, traversal)
        if isinstance(data.get("features"), EdgeFeatures):
            continue
        features = build_edge_features(
            graph,
            traversal.u,
            traversal.v,
            data,
            departure_time=departure_time,
            mode=mode,
            sample_spacing_m=sample_spacing_m,
            comfort_threshold=comfort_threshold,
            utci_raster_path=utci_raster_path,
            real_feature_context=real_feature_context,
        )
        data["features"] = features
        data["length"] = features.length_m
        data["travel_time"] = features.travel_time_s
    candidate = summarize_route(
        graph,
        traversals,
        preference=preference,
        departure_time=departure_time,
        utci_raster_path=utci_raster_path,
    )
    return RouteCandidate(
        geometry=candidate.geometry,
        edge_ids=candidate.edge_ids,
        distance_m=candidate.distance_m,
        duration_s=candidate.duration_s,
        mean_utci=candidate.mean_utci,
        max_utci=candidate.max_utci,
        heat_dose=candidate.heat_dose,
        shade_fraction=candidate.shade_fraction,
        scenic_score=candidate.scenic_score,
        noise_score=candidate.noise_score,
        slope_penalty=candidate.slope_penalty,
        cost=candidate.distance_m,
    )
