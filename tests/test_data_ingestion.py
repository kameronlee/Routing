from routing_backend.data_ingestion import build_synthetic_graph, nearest_node


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
