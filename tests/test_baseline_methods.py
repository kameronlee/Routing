import networkx as nx

from routing_backend.baseline_methods import (
    RouteMethod,
    available_methods,
    get_method_config,
    get_method_preference,
    project_graph_for_method,
    route_with_method,
)
from routing_backend.benchmark_runner import ROUTE_SUMMARY_COLUMNS
from routing_backend.route_engine import EdgeFeatures


def _features(length: float, utci: float, shade: float) -> EdgeFeatures:
    return EdgeFeatures(
        length_m=length,
        travel_time_s=length,
        mean_utci=utci,
        max_utci=utci + 2,
        heat_dose=max(0.0, utci - 26.0),
        shade_fraction=shade,
        scenic_score=0.5,
        noise_score=0.5,
        slope=0.0,
        elevation_change_m=0.0,
    )


def _graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node("a", y=0.0, x=0.0)
    graph.add_node("b", y=0.0, x=0.001)
    graph.add_node("c", y=0.001, x=0.0)
    graph.add_node("d", y=0.001, x=0.001)
    graph.add_edge("a", "b", length=100, geometry_points=[(0, 0), (0, 0.001)], features=_features(100, 34, 0.0))
    graph.add_edge("b", "d", length=100, geometry_points=[(0, 0.001), (0.001, 0.001)], features=_features(100, 34, 0.0))
    graph.add_edge("a", "c", length=120, geometry_points=[(0, 0), (0.001, 0)], features=_features(120, 23, 1.0))
    graph.add_edge("c", "d", length=120, geometry_points=[(0.001, 0), (0.001, 0.001)], features=_features(120, 23, 1.0))
    return graph


def test_available_methods_and_configs() -> None:
    methods = available_methods()

    assert "proposed_full" in methods
    assert "shortest_distance" in methods
    assert get_method_config("weighted_sum", comfort_threshold=26).enforce_detour is False
    assert get_method_preference("mean_utci", 26).comfort_threshold == 26


def test_project_graph_for_shadow_only_neutralizes_utci_terms() -> None:
    projected = project_graph_for_method(_graph(), RouteMethod.SHADOW_ONLY, comfort_threshold=26)
    features = next(iter(projected.edges(data=True)))[2]["features"]

    assert features.mean_utci == 26
    assert features.max_utci == 26
    assert features.heat_dose == 0


def test_project_graph_can_disable_utci_without_removing_shade() -> None:
    projected = project_graph_for_method(
        _graph(),
        RouteMethod.PROPOSED_FULL,
        comfort_threshold=26,
        disable_utci=True,
    )
    features = next(iter(projected.edges(data=True)))[2]["features"]

    assert features.mean_utci == 26
    assert features.max_utci == 26
    assert features.heat_dose == 0
    assert features.shade_fraction == 0.0


def test_route_with_method_respects_detour_for_proposed_full() -> None:
    route, config = route_with_method(
        _graph(),
        "a",
        "d",
        RouteMethod.PROPOSED_FULL,
        detour_ratio=0.25,
        comfort_threshold=26,
    )

    assert config.enforce_detour is True
    assert route.edge_ids == ["a->c:0", "c->d:0"]
    assert route.distance_m == 240


def test_route_with_method_shortest_distance() -> None:
    route, _config = route_with_method(
        _graph(),
        "a",
        "d",
        RouteMethod.SHORTEST_DISTANCE,
        detour_ratio=0.25,
        comfort_threshold=26,
    )

    assert route.edge_ids == ["a->b:0", "b->d:0"]
    assert route.distance_m == 200


def test_route_output_columns_include_required_fields() -> None:
    for column in ["pair_id", "method", "detour_ratio", "heat_dose", "success", "config_hash"]:
        assert column in ROUTE_SUMMARY_COLUMNS
