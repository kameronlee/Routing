"""Routing method adapters used by paper experiments."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
from typing import Any

import networkx as nx

from routing_backend.preferences import Preference
from routing_backend.route_engine import (
    EdgeFeatures,
    EdgeTraversal,
    RouteCandidate,
    _best_edge_between,
    _edge_features,
    _minimum_edge_cost,
    length_shortest_route_candidate,
    resource_constrained_routes,
    summarize_route,
)


class RouteMethod(str, Enum):
    """Named route methods for computational benchmarks."""

    SHORTEST_DISTANCE = "shortest_distance"
    AZIMUTH_HEURISTIC = "azimuth_heuristic"
    SHADOW_ONLY = "shadow_only"
    MEAN_UTCI = "mean_utci"
    MAX_UTCI = "max_utci"
    HEAT_DOSE = "heat_dose"
    WEIGHTED_SUM = "weighted_sum"
    PROPOSED_FULL = "proposed_full"


@dataclass(frozen=True)
class MethodConfig:
    """Routing-method configuration used by adapters."""

    method: RouteMethod
    preference: Preference
    enforce_detour: bool
    feature_projection: str
    description: str


def available_methods() -> list[str]:
    """Return all implemented benchmark method names."""

    return [method.value for method in RouteMethod]


def parse_method(value: str | RouteMethod) -> RouteMethod:
    """Parse a method name."""

    if isinstance(value, RouteMethod):
        return value
    try:
        return RouteMethod(value)
    except ValueError as exc:
        raise ValueError(f"Unknown route method {value!r}. Expected one of: {', '.join(available_methods())}") from exc


def get_method_config(method: str | RouteMethod, *, comfort_threshold: float) -> MethodConfig:
    """Return preference/projection settings for a route method."""

    route_method = parse_method(method)
    base = Preference(
        weight_cool=1.0,
        weight_scenic=0.45,
        weight_quiet=0.45,
        weight_slope=0.35,
        weight_time=0.20,
        weight_distance=0.15,
        uncertainty_penalty=0.15,
        comfort_threshold=comfort_threshold,
    )
    if route_method == RouteMethod.SHORTEST_DISTANCE:
        return MethodConfig(route_method, base, True, "none", "Length-shortest route; thermal metrics are reporting only.")
    if route_method == RouteMethod.AZIMUTH_HEURISTIC:
        return MethodConfig(
            route_method,
            base.with_overrides(weight_cool=2.0, weight_scenic=0.0, weight_quiet=0.0, weight_slope=0.0),
            True,
            "azimuth",
            "Solar azimuth/altitude shade fallback without the direct-shadow raster.",
        )
    if route_method == RouteMethod.SHADOW_ONLY:
        return MethodConfig(
            route_method,
            base.with_overrides(weight_cool=2.0, weight_scenic=0.0, weight_quiet=0.0, weight_slope=0.0),
            True,
            "shadow_only",
            "Direct-shadow objective using raster-derived shade fraction.",
        )
    if route_method == RouteMethod.MEAN_UTCI:
        return MethodConfig(
            route_method,
            base.with_overrides(weight_cool=2.0, weight_scenic=0.0, weight_quiet=0.0, weight_slope=0.0),
            True,
            "mean_utci",
            "Mean UTCI objective with other comfort terms neutralized.",
        )
    if route_method == RouteMethod.MAX_UTCI:
        return MethodConfig(
            route_method,
            base.with_overrides(weight_cool=2.0, weight_scenic=0.0, weight_quiet=0.0, weight_slope=0.0),
            True,
            "max_utci",
            "Peak UTCI objective with other comfort terms neutralized.",
        )
    if route_method == RouteMethod.HEAT_DOSE:
        return MethodConfig(
            route_method,
            base.with_overrides(weight_cool=2.0, weight_scenic=0.0, weight_quiet=0.0, weight_slope=0.0),
            True,
            "heat_dose",
            "Heat-dose objective above the configured comfort threshold.",
        )
    if route_method == RouteMethod.WEIGHTED_SUM:
        return MethodConfig(
            route_method,
            base,
            False,
            "none",
            "Unconstrained scalar weighted-cost path; detour is measured after routing.",
        )
    return MethodConfig(route_method, base, True, "none", "Full radiative-perceptual objective with hard detour constraint.")


def get_method_preference(method: str | RouteMethod, comfort_threshold: float) -> Preference:
    """Return only the preference object for a benchmark method."""

    return get_method_config(method, comfort_threshold=comfort_threshold).preference


def project_graph_for_method(
    graph: nx.MultiDiGraph,
    method: str | RouteMethod,
    *,
    comfort_threshold: float,
    utci_offset_c: float = 0.0,
    shade_fraction_flip_rate: float = 0.0,
    disable_utci: bool = False,
    disable_scenic: bool = False,
    disable_noise: bool = False,
    disable_uncertainty: bool = False,
) -> nx.MultiDiGraph:
    """Return a graph copy with method-specific feature projections."""

    route_method = parse_method(method)
    projected = graph.copy()
    for _u, _v, data in projected.edges(data=True):
        features = _edge_features(data)
        updated = _apply_common_feature_perturbations(
            features,
            comfort_threshold=comfort_threshold,
            utci_offset_c=utci_offset_c,
            shade_fraction_flip_rate=shade_fraction_flip_rate,
            disable_utci=disable_utci,
            disable_scenic=disable_scenic,
            disable_noise=disable_noise,
            disable_uncertainty=disable_uncertainty,
        )
        if route_method == RouteMethod.SHADOW_ONLY:
            updated = replace(
                updated,
                mean_utci=comfort_threshold,
                max_utci=comfort_threshold,
                heat_dose=0.0,
            )
        elif route_method == RouteMethod.MEAN_UTCI:
            updated = replace(
                updated,
                max_utci=comfort_threshold,
                heat_dose=0.0,
                shade_fraction=1.0,
            )
        elif route_method == RouteMethod.MAX_UTCI:
            updated = replace(
                updated,
                mean_utci=comfort_threshold,
                heat_dose=0.0,
                shade_fraction=1.0,
            )
        elif route_method == RouteMethod.HEAT_DOSE:
            updated = replace(
                updated,
                mean_utci=comfort_threshold,
                max_utci=comfort_threshold,
                shade_fraction=1.0,
            )
        data["features"] = updated
        data["length"] = updated.length_m
        data["travel_time"] = updated.travel_time_s
    return projected


def route_with_method(
    graph: nx.MultiDiGraph,
    origin_node: Any,
    destination_node: Any,
    method: str | RouteMethod,
    *,
    detour_ratio: float,
    comfort_threshold: float,
    departure_time: object | None = None,
    utci_raster_path: str | None = None,
    max_labels_per_node: int = 8,
    max_expansions: int | None = None,
    max_seconds: float | None = None,
    maximum_distance_m: float | None = None,
    preference_overrides: dict[str, float] | None = None,
) -> tuple[RouteCandidate, MethodConfig]:
    """Run one benchmark method on an already-featured graph."""

    method_config = get_method_config(method, comfort_threshold=comfort_threshold)
    if preference_overrides:
        if any(not math.isfinite(value) or value < 0 for value in preference_overrides.values()):
            raise ValueError("Preference weights must be finite and non-negative")
        if any(not name.startswith("weight_") and name != "uncertainty_penalty" for name in preference_overrides):
            raise ValueError("Only objective weights may be overridden")
        method_config = replace(method_config, preference=method_config.preference.with_overrides(**preference_overrides))
    preference = method_config.preference
    route_method = method_config.method
    if route_method == RouteMethod.SHORTEST_DISTANCE:
        return (
            replace(length_shortest_route_candidate(
                graph,
                origin_node,
                destination_node,
                preference,
                departure_time=departure_time,
                utci_raster_path=utci_raster_path,
            ), route_source="shortest_distance", maximum_distance_m=maximum_distance_m),
            method_config,
        )
    if route_method == RouteMethod.WEIGHTED_SUM:
        return (
            replace(_unconstrained_cost_shortest_route(
                graph,
                origin_node,
                destination_node,
                preference,
                departure_time=departure_time,
                utci_raster_path=utci_raster_path,
            ), route_source="unconstrained_weighted_sum"),
            method_config,
        )

    method_graph = project_graph_for_method(
        graph,
        route_method,
        comfort_threshold=comfort_threshold,
    )
    routes = resource_constrained_routes(
        method_graph,
        origin_node,
        destination_node,
        preference,
        delta=detour_ratio,
        max_candidates=1,
        max_labels_per_node=max_labels_per_node,
        max_expansions=max_expansions,
        max_seconds=max_seconds,
        departure_time=departure_time,
        utci_raster_path=utci_raster_path,
        maximum_distance_m=maximum_distance_m,
    )
    reported_candidate = _rescore_candidate_on_graph(
        graph,
        routes[0],
        preference,
        departure_time=departure_time,
        utci_raster_path=utci_raster_path,
    )
    return reported_candidate, method_config


def _apply_common_feature_perturbations(
    features: EdgeFeatures,
    *,
    comfort_threshold: float,
    utci_offset_c: float,
    shade_fraction_flip_rate: float,
    disable_utci: bool,
    disable_scenic: bool,
    disable_noise: bool,
    disable_uncertainty: bool,
) -> EdgeFeatures:
    mean_utci = features.mean_utci + utci_offset_c
    max_utci = features.max_utci + utci_offset_c
    # E[max(0, U-tau)] is not max(0, E[U]-tau). A no-op must
    # preserve the sampled exceedance, and threshold/offset sweeps need samples.
    heat_dose = features.heat_dose
    samples = features.utci_samples
    if utci_offset_c != 0.0 or comfort_threshold != features.utci_threshold_c:
        if not samples and not disable_utci:
            raise ValueError("UTCI perturbations require retained edge samples; rebuild the feature graph")
        samples = tuple(value + utci_offset_c for value in samples)
        if samples:
            heat_dose = sum(max(0.0, value - comfort_threshold) for value in samples) / len(samples)
    if disable_utci:
        mean_utci = comfort_threshold
        max_utci = comfort_threshold
        heat_dose = 0.0
    flip_rate = max(0.0, min(1.0, shade_fraction_flip_rate))
    shade_fraction = (
        features.shade_fraction * (1.0 - flip_rate)
        + (1.0 - features.shade_fraction) * flip_rate
    )
    return replace(
        features,
        mean_utci=mean_utci,
        max_utci=max_utci,
        heat_dose=heat_dose,
        shade_fraction=shade_fraction,
        scenic_score=0.5 if disable_scenic else features.scenic_score,
        noise_score=0.0 if disable_noise else features.noise_score,
        uncertainty=0.0 if disable_uncertainty else features.uncertainty,
        utci_samples=samples,
        utci_threshold_c=comfort_threshold,
    )


def _unconstrained_cost_shortest_route(
    graph: nx.MultiDiGraph,
    origin_node: Any,
    destination_node: Any,
    preference: Preference,
    *,
    departure_time: object | None,
    utci_raster_path: str | None,
) -> RouteCandidate:
    path_nodes = nx.shortest_path(
        graph,
        origin_node,
        destination_node,
        weight=lambda _u, _v, data: _minimum_edge_cost(data, preference),
    )
    traversals: list[EdgeTraversal] = [
        _best_edge_between(graph, u, v, preference)
        for u, v in zip(path_nodes, path_nodes[1:])
    ]
    return summarize_route(
        graph,
        traversals,
        preference,
        departure_time=departure_time,
        utci_raster_path=utci_raster_path,
    )


def _rescore_candidate_on_graph(
    graph: nx.MultiDiGraph,
    candidate: RouteCandidate,
    preference: Preference,
    *,
    departure_time: object | None,
    utci_raster_path: str | None,
) -> RouteCandidate:
    """Recompute reported metrics on the unprojected feature graph."""

    traversals = [_edge_id_to_traversal(graph, edge_id) for edge_id in candidate.edge_ids]
    rescored = summarize_route(
        graph,
        traversals,
        preference,
        departure_time=departure_time,
        utci_raster_path=utci_raster_path,
    )
    return RouteCandidate(
        geometry=rescored.geometry,
        edge_ids=rescored.edge_ids,
        distance_m=rescored.distance_m,
        duration_s=rescored.duration_s,
        mean_utci=rescored.mean_utci,
        max_utci=rescored.max_utci,
        heat_dose=rescored.heat_dose,
        shade_fraction=rescored.shade_fraction,
        scenic_score=rescored.scenic_score,
        noise_score=rescored.noise_score,
        slope_penalty=rescored.slope_penalty,
        cost=candidate.cost,
        route_source=candidate.route_source,
        search_truncated=candidate.search_truncated,
        search_stop_reason=candidate.search_stop_reason,
        expanded_labels=candidate.expanded_labels,
        retained_labels=candidate.retained_labels,
        maximum_distance_m=candidate.maximum_distance_m,
        shade_fallback_fraction=rescored.shade_fallback_fraction,
    )


def _edge_id_to_traversal(graph: nx.MultiDiGraph, edge_id: str) -> EdgeTraversal:
    if ":" in edge_id:
        uv_text, key_text = edge_id.rsplit(":", 1)
        u_text, v_text = uv_text.split("->", 1)
        u = _coerce_graph_node(graph, u_text)
        v = _coerce_graph_node(graph, v_text)
        edge_options = graph.get_edge_data(u, v) or {}
        key: Any = key_text
        if key not in edge_options:
            try:
                int_key = int(key_text)
            except ValueError:
                int_key = None
            if int_key is not None and int_key in edge_options:
                key = int_key
        return EdgeTraversal(u=u, v=v, key=key)
    u_text, v_text = edge_id.split("->", 1)
    return EdgeTraversal(u=_coerce_graph_node(graph, u_text), v=_coerce_graph_node(graph, v_text), key=None)


def _coerce_graph_node(graph: nx.Graph, value: str) -> Any:
    if value in graph:
        return value
    for node in graph.nodes:
        if str(node) == value:
            return node
    return value
