"""Feature extraction, utility scoring and constrained path search."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import heapq
import itertools
from pathlib import Path
from statistics import fmean
from typing import Any, Hashable, Iterable, Sequence

import networkx as nx

try:
    from shapely import wkt
except ImportError:  # pragma: no cover - optional OSM GraphML geometry support
    wkt = None  # type: ignore[assignment]

from routing_backend.microclimate_model import (
    Coordinate,
    haversine_distance_m,
    sample_microclimate_along_geometry,
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
    sample_spacing_m: float = 5.0,
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
    climate = sample_microclimate_along_geometry(
        points,
        departure_time=departure_time,
        spacing_m=sample_spacing_m,
        comfort_threshold=comfort_threshold,
        raster_path=utci_raster_path,
    )
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
        shade_fraction=climate.shade_fraction,
        scenic_score=float(data.get("scenic_score", compute_scenic_score(data))),
        noise_score=float(data.get("noise_score", compute_noise_score(data))),
        slope=slope,
        elevation_change_m=elevation_change_m,
        poi_density=float(data.get("poi_density", 0.0)),
        uncertainty=float(data.get("feature_uncertainty", 0.15 if data.get("source") == "synthetic" else 0.05)),
    )


def build_feature_graph(
    graph: nx.MultiDiGraph,
    departure_time: datetime | float | int | None,
    mode: str = "walk",
    sample_spacing_m: float = 5.0,
    comfort_threshold: float = 26.0,
    utci_raster_path: str | Path | None = None,
    real_feature_context: Any | None = None,
) -> nx.MultiDiGraph:
    """Return a graph copy whose edges contain ``EdgeFeatures`` objects."""

    feature_graph = graph.copy()
    if feature_graph.is_multigraph():
        edge_iter = feature_graph.edges(keys=True, data=True)
        for u, v, _key, data in edge_iter:
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
            data["features"] = features
            data["length"] = features.length_m
            data["travel_time"] = features.travel_time_s
    else:
        for u, v, data in feature_graph.edges(data=True):
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
            data["features"] = features
            data["length"] = features.length_m
            data["travel_time"] = features.travel_time_s
    return feature_graph


def cost(features: EdgeFeatures, pref: Preference) -> float:
    """Convert an edge feature vector and user preference into scalar cost."""

    cool_penalty = (
        max(0.0, features.mean_utci - pref.comfort_threshold) / 8.0
        + max(0.0, features.max_utci - pref.comfort_threshold) / 10.0
        + features.heat_dose / 6.0
        + (1.0 - features.shade_fraction) * 0.45
    )
    scenic_penalty = 1.0 - features.scenic_score
    slope_penalty = abs(features.slope) * 10.0 + max(0.0, features.elevation_change_m) / 25.0

    scalar = (
        pref.weight_distance * (features.length_m / 1_000.0)
        + pref.weight_time * (features.travel_time_s / 600.0)
        + pref.weight_cool * cool_penalty
        + pref.weight_scenic * scenic_penalty
        + pref.weight_quiet * features.noise_score
        + pref.weight_slope * slope_penalty
        + pref.uncertainty_penalty * features.uncertainty
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


def resource_constrained_routes(
    graph: nx.MultiDiGraph,
    origin_node: Hashable,
    destination_node: Hashable,
    preference: Preference,
    delta: float = 0.20,
    max_candidates: int = 3,
    max_labels_per_node: int = 30,
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
    candidates: list[RouteCandidate] = []
    seen_edge_sequences: set[tuple[EdgeTraversal, ...]] = set()

    while queue and len(candidates) < max_candidates:
        path_cost, _order, node, length_m, path_nodes, path_edges = heapq.heappop(queue)

        if node == destination_node:
            signature = tuple(path_edges)
            if signature not in seen_edge_sequences:
                seen_edge_sequences.add(signature)
                candidates.append(
                    summarize_route(
                        graph,
                        path_edges,
                        preference,
                        path_cost=path_cost,
                        departure_time=departure_time,
                        utci_raster_path=utci_raster_path,
                    )
                )
            continue

        for u, v, key, data in _out_edges(graph, node):
            if v in path_nodes:
                continue
            features = _edge_features(data)
            next_length = length_m + features.length_m
            if next_length > maximum_distance + 1e-9:
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
    climate = sample_microclimate_along_geometry(
        geometry,
        departure_time=departure_time,
        comfort_threshold=preference.comfort_threshold,
        raster_path=utci_raster_path,
    )

    total_weight = sum(weights)
    scenic_score = sum(feature.scenic_score * weight for feature, weight in zip(features, weights)) / total_weight
    noise_score = sum(feature.noise_score * weight for feature, weight in zip(features, weights)) / total_weight
    slope_penalty = fmean(abs(feature.slope) for feature in features)
    scalar_cost = path_cost if path_cost is not None else sum(cost(feature, preference) for feature in features)

    return RouteCandidate(
        geometry=geometry,
        edge_ids=[
            f"{traversal.u}->{traversal.v}" if traversal.key is None else f"{traversal.u}->{traversal.v}:{traversal.key}"
            for traversal in traversals
        ],
        distance_m=distance_m,
        duration_s=duration_s,
        mean_utci=climate.mean_utci,
        max_utci=climate.max_utci,
        heat_dose=climate.heat_dose,
        shade_fraction=climate.shade_fraction,
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
