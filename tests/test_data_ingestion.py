from routing_backend.data_ingestion import (
    build_synthetic_graph,
    clip_graph_to_candidate_paths,
    clip_graph_to_detour_corridor,
    nearest_node,
)


def test_synthetic_graph_has_geocoded_edges() -> None:
    graph = build_synthetic_graph(grid_size=4)

    assert graph.number_of_nodes() == 16
    assert graph.number_of_edges() > 0
    _, _, data = next(iter(graph.edges(data=True)))
    assert "length" in data
    assert "geometry_points" in data


def test_nearest_node_returns_node_id() -> None:
    graph = build_synthetic_graph(grid_size=3)
    node = nearest_node(graph, (38.8816, -77.0910))

    assert node in graph.nodes


def test_detour_corridor_uses_network_distance_bounds() -> None:
    graph = build_synthetic_graph(grid_size=5, spacing_m=100)

    clipped = clip_graph_to_detour_corridor(
        graph,
        "n2_0",
        "n2_4",
        maximum_distance_m=410,
        margin_m=0,
        minimum_nodes=2,
    )

    assert {"n2_0", "n2_1", "n2_2", "n2_3", "n2_4"} <= set(clipped.nodes)
    assert clipped.number_of_nodes() < graph.number_of_nodes()


def test_candidate_path_clip_bounds_expensive_feature_subgraph() -> None:
    graph = build_synthetic_graph(grid_size=5, spacing_m=100)

    clipped = clip_graph_to_candidate_paths(
        graph,
        "n0_0",
        "n4_4",
        maximum_distance_m=900,
        max_paths=3,
    )

    assert clipped.graph["candidate_path_count"] == 3
    assert len(clipped.graph["candidate_node_paths"]) == 3
    assert all(path[0] == "n0_0" and path[-1] == "n4_4" for path in clipped.graph["candidate_node_paths"])
    assert clipped.number_of_edges() < graph.number_of_edges()
    assert "n0_0" in clipped and "n4_4" in clipped
