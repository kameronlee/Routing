import networkx as nx

from routing_backend.preferences import Preference
from routing_backend.route_engine import EdgeFeatures, resource_constrained_routes


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
