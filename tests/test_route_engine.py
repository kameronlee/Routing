from datetime import datetime

import networkx as nx
import pytest

from routing_backend import route_engine
from routing_backend.preferences import Preference
from routing_backend.route_engine import (
    EdgeFeatures,
    build_feature_graph,
    cost,
    length_shortest_route_candidate,
    resource_constrained_routes,
)


def _features(length: float, utci: float, scenic: float, noise: float) -> EdgeFeatures:
    return EdgeFeatures(
        length_m=length,
        travel_time_s=length,
        mean_utci=utci,
        max_utci=utci + 1,
        heat_dose=max(0, utci - 26),
        shade_fraction=1.0 if utci < 26 else 0.0,
        scenic_score=scenic,
        noise_score=noise,
        slope=0.0,
        elevation_change_m=0.0,
    )


def _test_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node("a", y=0.0, x=0.0, elevation=0)
    graph.add_node("b", y=0.0, x=0.001, elevation=0)
    graph.add_node("c", y=0.001, x=0.0, elevation=0)
    graph.add_node("d", y=0.001, x=0.001, elevation=0)
    graph.add_edge(
        "a",
        "b",
        length=100,
        geometry_points=[(0.0, 0.0), (0.0, 0.001)],
        features=_features(100, 34, 0.2, 0.9),
    )
    graph.add_edge(
        "b",
        "d",
        length=100,
        geometry_points=[(0.0, 0.001), (0.001, 0.001)],
        features=_features(100, 34, 0.2, 0.9),
    )
    graph.add_edge(
        "a",
        "c",
        length=120,
        geometry_points=[(0.0, 0.0), (0.001, 0.0)],
        features=_features(120, 23, 0.9, 0.1),
    )
    graph.add_edge(
        "c",
        "d",
        length=120,
        geometry_points=[(0.001, 0.0), (0.001, 0.001)],
        features=_features(120, 23, 0.9, 0.1),
    )
    return graph


def test_constrained_search_prefers_cool_route_when_budget_allows() -> None:
    graph = _test_graph()
    pref = Preference(weight_cool=2.0, weight_scenic=1.0, weight_quiet=1.0, weight_distance=0.0)

    routes = resource_constrained_routes(graph, "a", "d", pref, delta=0.25, max_candidates=1)

    assert routes[0].edge_ids == ["a->c:0", "c->d:0"]
    assert routes[0].distance_m == 240


def test_constrained_search_respects_distance_budget() -> None:
    graph = _test_graph()
    pref = Preference(weight_cool=2.0, weight_scenic=1.0, weight_quiet=1.0, weight_distance=0.0)

    routes = resource_constrained_routes(graph, "a", "d", pref, delta=0.05, max_candidates=1)

    assert routes[0].edge_ids == ["a->b:0", "b->d:0"]
    assert routes[0].distance_m == 200


def test_constrained_search_reports_expansion_budget() -> None:
    graph = _test_graph()
    pref = Preference(weight_cool=2.0, weight_scenic=1.0, weight_quiet=1.0, weight_distance=0.0)

    with pytest.raises(RuntimeError, match="expansion budget"):
        resource_constrained_routes(graph, "a", "d", pref, delta=0.05, max_candidates=1, max_expansions=1)


def test_shade_weight_increases_sun_exposure_cost() -> None:
    features = _features(100, 30, 0.5, 0.5)

    base_cost = cost(features, Preference(weight_cool=1.0, weight_shade=1.0))
    shade_heavy_cost = cost(features, Preference(weight_cool=1.0, weight_shade=2.0))

    assert shade_heavy_cost > base_cost


def test_build_feature_graph_removes_edges_without_utci_coverage(monkeypatch) -> None:
    graph = nx.MultiDiGraph()
    graph.add_node("a", y=0.0, x=0.0)
    graph.add_node("b", y=0.0, x=0.001)
    graph.add_node("c", y=0.001, x=0.001)
    graph.add_edge("a", "b", length=100)
    graph.add_edge("b", "c", length=100)

    def fake_build_edge_features(_graph, u, v, *_args, **_kwargs):
        if (u, v) == ("a", "b"):
            raise ValueError("No valid UTCI samples found in raster example.tif")
        return _features(100, 30, 0.5, 0.5)

    monkeypatch.setattr(route_engine, "build_edge_features", fake_build_edge_features)

    feature_graph = build_feature_graph(graph, departure_time=None, utci_raster_path="example.tif")

    assert not feature_graph.has_edge("a", "b")
    assert feature_graph.has_edge("b", "c")
    assert feature_graph.graph["removed_no_utci_edges"] == 1


def test_build_feature_graph_uses_direct_shadow_fraction_when_available() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node("a", y=0.0, x=0.0)
    graph.add_node("b", y=0.0, x=0.001)
    graph.add_edge("a", "b", length=100)

    class FakeRealContext:
        def edge_attributes_many(self, edge_groups):
            return [
                {
                    "scenic_score": 0.5,
                    "noise_score": 0.5,
                    "feature_uncertainty": 0.0,
                }
                for _edge in edge_groups
            ]

        def utci_values_many(self, point_groups):
            return [[35.0 for _point in points] for points in point_groups]

        def shadow_values_many(self, point_groups):
            return [[0.0, 1.0, 0.0] for _points in point_groups]

    feature_graph = build_feature_graph(graph, departure_time=None, real_feature_context=FakeRealContext())
    features = next(iter(feature_graph.edges(data=True)))[2]["features"]

    assert features.mean_utci == 35.0
    assert features.shade_fraction == 2 / 3


def test_build_edge_features_uses_azimuth_shade_fallback_without_shadow() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node("a", y=38.8895, x=-76.9840, elevation=0)
    graph.add_node("b", y=38.8895, x=-76.9830, elevation=0)
    edge_data = {
        "length": 100,
        "geometry_points": [(38.8895, -76.9840), (38.8895, -76.9830)],
        "tree_canopy_fraction": 0.72,
        "canopy_height_mean_m": 8.0,
        "width": 10.0,
    }
    graph.add_edge("a", "b", **edge_data)

    features = route_engine.build_edge_features(
        graph,
        "a",
        "b",
        edge_data,
        departure_time=datetime(2026, 6, 19, 14, 0),
        sample_spacing_m=1000,
    )

    assert features.shade_fraction >= 0.72


def test_length_shortest_route_candidate_uses_true_shortest_path() -> None:
    graph = _test_graph()
    pref = Preference(weight_cool=2.0, weight_scenic=1.0, weight_quiet=1.0, weight_distance=0.0)

    route = length_shortest_route_candidate(graph, "a", "d", pref)

    assert route.edge_ids == ["a->b:0", "b->d:0"]
    assert route.distance_m == 200
    assert route.cost == 200
