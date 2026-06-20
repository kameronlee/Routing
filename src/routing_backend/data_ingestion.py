"""Street graph ingestion and development fallback graph generation."""

from __future__ import annotations

from datetime import UTC, datetime
import math
from pathlib import Path
from typing import Any

import networkx as nx

from routing_backend.microclimate_model import (
    Coordinate,
    haversine_distance_m,
    offset_coordinate,
)


def build_synthetic_graph(
    center: Coordinate = (38.8816, -77.0910),
    grid_size: int = 5,
    spacing_m: float = 120.0,
) -> nx.MultiDiGraph:
    """Build a deterministic walkable grid when OSM data is unavailable."""

    if grid_size < 2:
        raise ValueError("grid_size must be at least 2")

    graph = nx.MultiDiGraph()
    graph.graph["source"] = "synthetic"
    graph.graph["created_at"] = datetime.now(UTC).isoformat()
    midpoint = (grid_size - 1) / 2.0

    for row in range(grid_size):
        for col in range(grid_size):
            lat, lon = offset_coordinate(
                center,
                north_m=(row - midpoint) * spacing_m,
                east_m=(col - midpoint) * spacing_m,
            )
            elevation = 35.0 + 1.7 * row + 0.8 * col
            graph.add_node(f"n{row}_{col}", y=lat, x=lon, elevation=elevation)

    def add_bidirectional_edge(u: str, v: str, **attrs: Any) -> None:
        u_data = graph.nodes[u]
        v_data = graph.nodes[v]
        points = [(u_data["y"], u_data["x"]), (v_data["y"], v_data["x"])]
        length_m = haversine_distance_m(points[0], points[1])
        common = {
            "length": length_m,
            "geometry_points": points,
            **attrs,
        }
        graph.add_edge(u, v, **common)
        reverse = {
            **common,
            "geometry_points": list(reversed(points)),
        }
        graph.add_edge(v, u, **reverse)

    park_row = grid_size // 2
    busy_col = max(1, grid_size // 2 - 1)

    for row in range(grid_size):
        for col in range(grid_size):
            node = f"n{row}_{col}"
            if col + 1 < grid_size:
                highway = "path" if row == park_row else "residential"
                add_bidirectional_edge(
                    node,
                    f"n{row}_{col + 1}",
                    highway=highway,
                    landuse="park" if row == park_row else "residential",
                    tree_canopy_fraction=0.72 if row == park_row else 0.28,
                    gps_trajectory_intensity=0.20 if row == park_row else 0.42,
                )
            if row + 1 < grid_size:
                highway = "primary" if col == busy_col else "residential"
                add_bidirectional_edge(
                    node,
                    f"n{row + 1}_{col}",
                    highway=highway,
                    lanes=3 if col == busy_col else 1,
                    tree_canopy_fraction=0.16 if col == busy_col else 0.36,
                    gps_trajectory_intensity=0.82 if col == busy_col else 0.34,
                )

    return graph


def download_osm_graph(
    place: str,
    network_type: str = "walk",
    fallback_center: Coordinate = (38.8816, -77.0910),
    allow_synthetic_fallback: bool = False,
) -> nx.MultiDiGraph:
    """Download a pedestrian/cycling graph with OSMnx."""

    try:
        import osmnx as ox  # type: ignore
    except ImportError:
        if allow_synthetic_fallback:
            return build_synthetic_graph(center=fallback_center)
        raise RuntimeError("OSMnx is required to download real OSM street graphs")

    try:
        graph = ox.graph_from_place(place, network_type=network_type, simplify=True)
        graph = ox.distance.add_edge_lengths(graph)
        graph.graph["source"] = f"osmnx:{place}"
        return graph
    except Exception:
        if allow_synthetic_fallback:
            return build_synthetic_graph(center=fallback_center)
        raise


def load_street_graph(graph_path: str | Path) -> nx.MultiDiGraph:
    """Load a preprocessed street graph from GraphML."""

    path = Path(graph_path)
    try:
        import osmnx as ox  # type: ignore

        graph = ox.load_graphml(path)
    except Exception:
        graph = nx.read_graphml(path)

    graph = nx.MultiDiGraph(graph)
    for _node, data in graph.nodes(data=True):
        if "x" in data:
            data["x"] = float(data["x"])
        if "y" in data:
            data["y"] = float(data["y"])
        if "elevation" in data:
            try:
                data["elevation"] = float(data["elevation"])
            except (TypeError, ValueError):
                data.pop("elevation", None)

    for _u, _v, data in graph.edges(data=True):
        for attribute in ("length", "travel_time"):
            if attribute in data:
                try:
                    data[attribute] = float(data[attribute])
                except (TypeError, ValueError):
                    data.pop(attribute, None)
    graph.graph["source"] = f"graphml:{path.name}"
    return graph


def apply_node_elevations_from_dem(graph: nx.MultiDiGraph, dem_path: str | Path | None) -> nx.MultiDiGraph:
    """Return a graph copy with node elevations sampled from a DEM GeoTIFF."""

    if dem_path is None:
        return graph

    path = Path(dem_path)
    if not path.exists():
        return graph

    try:
        from routing_backend.raster_data import sample_raster_values
    except Exception:
        return graph

    updated = graph.copy()
    nodes = [
        (node, (float(data["y"]), float(data["x"])))
        for node, data in updated.nodes(data=True)
        if "y" in data and "x" in data
    ]
    if not nodes:
        return updated

    values = sample_raster_values(path, [coordinate for _node, coordinate in nodes])
    if len(values) != len(nodes):
        return updated

    for (node, _coordinate), elevation in zip(nodes, values):
        updated.nodes[node]["elevation"] = elevation
    updated.graph["elevation_source"] = str(path)
    return updated


def clip_graph_to_route_area(
    graph: nx.MultiDiGraph,
    origin: Coordinate,
    destination: Coordinate,
    *,
    buffer_m: float = 1_000.0,
    minimum_nodes: int = 50,
) -> nx.MultiDiGraph:
    """Clip a graph to a buffered origin/destination bounding box."""

    latitudes = [origin[0], destination[0]]
    longitudes = [origin[1], destination[1]]
    center_lat = sum(latitudes) / 2.0
    lat_buffer = buffer_m / 111_320.0
    lon_buffer = buffer_m / (111_320.0 * max(0.1, abs(math.cos(math.radians(center_lat)))))
    min_lat = min(latitudes) - lat_buffer
    max_lat = max(latitudes) + lat_buffer
    min_lon = min(longitudes) - lon_buffer
    max_lon = max(longitudes) + lon_buffer

    nodes = [
        node
        for node, data in graph.nodes(data=True)
        if "y" in data
        and "x" in data
        and min_lat <= float(data["y"]) <= max_lat
        and min_lon <= float(data["x"]) <= max_lon
    ]
    if len(nodes) < minimum_nodes:
        return graph

    clipped = graph.subgraph(nodes).copy()
    clipped.graph.update(graph.graph)
    clipped.graph["clipped_node_count"] = len(nodes)
    clipped.graph["clip_buffer_m"] = buffer_m
    return nx.MultiDiGraph(clipped)


def clip_graph_to_detour_corridor(
    graph: nx.MultiDiGraph,
    origin_node: Any,
    destination_node: Any,
    *,
    maximum_distance_m: float,
    margin_m: float = 50.0,
    minimum_nodes: int = 20,
) -> nx.MultiDiGraph:
    """Clip a graph to nodes that can still fit inside the detour budget."""

    if origin_node not in graph or destination_node not in graph:
        return graph

    origin_data = graph.nodes[origin_node]
    destination_data = graph.nodes[destination_node]
    if not {"y", "x"} <= origin_data.keys() or not {"y", "x"} <= destination_data.keys():
        return graph

    origin = (float(origin_data["y"]), float(origin_data["x"]))
    destination = (float(destination_data["y"]), float(destination_data["x"]))
    lower_bound_limit_m = maximum_distance_m + margin_m

    nodes = []
    for node, data in graph.nodes(data=True):
        if "y" not in data or "x" not in data:
            continue
        coordinate = (float(data["y"]), float(data["x"]))
        lower_bound_m = haversine_distance_m(origin, coordinate) + haversine_distance_m(coordinate, destination)
        if lower_bound_m <= lower_bound_limit_m:
            nodes.append(node)

    if origin_node not in nodes or destination_node not in nodes or len(nodes) < minimum_nodes:
        return graph

    clipped = graph.subgraph(nodes).copy()
    clipped.graph.update(graph.graph)
    clipped.graph["detour_corridor_node_count"] = len(nodes)
    clipped.graph["detour_corridor_maximum_distance_m"] = maximum_distance_m
    clipped.graph["detour_corridor_margin_m"] = margin_m
    return nx.MultiDiGraph(clipped)


def nearest_node(graph: nx.MultiDiGraph, coordinate: Coordinate) -> Any:
    """Find the nearest graph node to a ``(lat, lon)`` coordinate."""

    lat, lon = coordinate
    try:
        import osmnx as ox  # type: ignore

        return ox.distance.nearest_nodes(graph, X=lon, Y=lat)
    except Exception:
        best_node: Any | None = None
        best_distance = float("inf")
        for node, data in graph.nodes(data=True):
            if "y" not in data or "x" not in data:
                continue
            distance = haversine_distance_m((lat, lon), (float(data["y"]), float(data["x"])))
            if distance < best_distance:
                best_node = node
                best_distance = distance
        if best_node is None:
            raise ValueError("Graph contains no geocoded nodes")
        return best_node


def graph_center(graph: nx.MultiDiGraph) -> Coordinate:
    """Return the mean coordinate of all geocoded nodes in a graph."""

    latitudes = [float(data["y"]) for _, data in graph.nodes(data=True) if "y" in data]
    longitudes = [float(data["x"]) for _, data in graph.nodes(data=True) if "x" in data]
    if not latitudes or not longitudes:
        raise ValueError("Graph contains no geocoded nodes")
    return sum(latitudes) / len(latitudes), sum(longitudes) / len(longitudes)
