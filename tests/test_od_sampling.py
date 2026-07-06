import networkx as nx
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from routing_backend.od_sampling import (
    filter_pairs_by_shortest_distance,
    generate_candidate_pairs,
    generate_od_pairs,
    largest_relevant_component,
    load_graph_for_sampling,
    nodes_inside_raster_bounds,
)


def _graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node("a", y=38.99, x=-76.99)
    graph.add_node("b", y=38.99, x=-76.98)
    graph.add_node("c", y=38.98, x=-76.98)
    graph.add_edge("a", "b", length=100)
    graph.add_edge("b", "c", length=150)
    graph.add_edge("a", "c", length=400)
    return graph


def _write_raster(path) -> None:
    values = np.ones((4, 4), dtype=np.float32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-77.0, 39.0, 0.01, 0.01),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(values, 1)


def test_nodes_inside_raster_bounds(tmp_path) -> None:
    raster = tmp_path / "coverage.tif"
    _write_raster(raster)

    nodes = nodes_inside_raster_bounds(_graph(), [raster], require_values=True)

    assert set(nodes) == {"a", "b", "c"}


def test_filter_pairs_by_shortest_distance_respects_range() -> None:
    pairs = filter_pairs_by_shortest_distance(
        _graph(),
        [("a", "c"), ("a", "b")],
        min_distance_m=200,
        max_distance_m=300,
    )

    assert len(pairs) == 1
    assert pairs[0].origin_node == "a"
    assert pairs[0].destination_node == "c"
    assert pairs[0].baseline_shortest_distance_m == 250


def test_generate_candidate_pairs_is_seeded() -> None:
    nodes = ["a", "b", "c"]

    assert generate_candidate_pairs(nodes, 3, seed=42) == generate_candidate_pairs(nodes, 3, seed=42)


def test_largest_relevant_component() -> None:
    graph = _graph()
    graph.add_node("isolated", y=0, x=0)

    component = largest_relevant_component(graph)

    assert set(component.nodes) == {"a", "b", "c"}


def test_load_graph_for_sampling_reads_minimal_graphml(tmp_path) -> None:
    graph = nx.MultiDiGraph()
    graph.add_node("a", y=38.99, x=-76.99, ignored="extra")
    graph.add_node("b", y=38.98, x=-76.98)
    graph.add_edge("a", "b", length=123.4, geometry="LINESTRING (-76.99 38.99, -76.98 38.98)")
    path = tmp_path / "sample.graphml"
    nx.write_graphml(graph, path)

    loaded = load_graph_for_sampling(path)

    assert loaded.graph["sampling_loader"] == "minimal_graphml"
    assert loaded.nodes["a"]["x"] == -76.99
    assert loaded.nodes["b"]["y"] == 38.98
    assert next(iter(loaded["a"]["b"].values()))["length"] == 123.4


def test_generate_od_pairs_fails_clearly_without_raster_coverage(tmp_path) -> None:
    raster = tmp_path / "coverage.tif"
    _write_raster(raster)
    graph = _graph()
    for node in graph.nodes:
        graph.nodes[node]["x"] = -70.0
        graph.nodes[node]["y"] = 35.0

    with pytest.raises(RuntimeError, match="fewer than two graph nodes"):
        generate_od_pairs(
            graph,
            [raster],
            pair_count=1,
            seed=42,
            min_distance_m=10,
            max_distance_m=500,
        )
