"""Origin-destination sampling utilities for routing benchmarks."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import random
from typing import Any, Iterable, Sequence

import networkx as nx

from routing_backend.data_ingestion import load_street_graph
from routing_backend.microclimate_model import Coordinate, haversine_distance_m


@dataclass(frozen=True)
class ODPair:
    """One benchmark origin-destination pair."""

    pair_id: str
    origin_node: Any
    destination_node: Any
    origin_lat: float
    origin_lon: float
    destination_lat: float
    destination_lon: float
    baseline_shortest_distance_m: float
    component_id: int | None = None
    notes: str = ""

    def to_row(self) -> dict[str, Any]:
        """Return a CSV-ready dictionary."""

        return {
            "pair_id": self.pair_id,
            "origin_node": self.origin_node,
            "destination_node": self.destination_node,
            "origin_lat": self.origin_lat,
            "origin_lon": self.origin_lon,
            "destination_lat": self.destination_lat,
            "destination_lon": self.destination_lon,
            "baseline_shortest_distance_m": self.baseline_shortest_distance_m,
            "component_id": self.component_id,
            "notes": self.notes,
        }


OD_PAIR_COLUMNS = [
    "pair_id",
    "origin_node",
    "destination_node",
    "origin_lat",
    "origin_lon",
    "destination_lat",
    "destination_lon",
    "baseline_shortest_distance_m",
    "component_id",
    "notes",
]


def load_graph_for_sampling(graph_path: str | Path) -> nx.MultiDiGraph:
    """Load a real GraphML street graph for experiment OD sampling."""

    path = Path(graph_path)
    if not path.exists():
        raise FileNotFoundError(f"GraphML path does not exist: {path}")
    if path.suffix.lower() == ".graphml":
        try:
            graph = _load_graphml_for_sampling(path)
        except Exception:
            graph = load_street_graph(path)
    else:
        graph = load_street_graph(path)
    if graph.number_of_nodes() == 0:
        raise ValueError(f"Graph contains no nodes: {path}")
    return graph


def _load_graphml_for_sampling(path: Path) -> nx.MultiDiGraph:
    """Read only node coordinates and edge lengths needed for OD sampling."""

    import xml.etree.ElementTree as ET

    graph = nx.MultiDiGraph()
    node_keys: dict[str, str] = {}
    edge_keys: dict[str, str] = {}

    context = ET.iterparse(path, events=("start", "end"))
    _event, root = next(context)

    for event, element in context:
        if event != "end":
            continue
        tag = _graphml_local_name(element.tag)
        if tag == "key":
            key_id = element.attrib.get("id")
            key_for = element.attrib.get("for")
            key_name = element.attrib.get("attr.name")
            if key_id and key_for == "node" and key_name in {"x", "y"}:
                node_keys[key_id] = key_name
            elif key_id and key_for == "edge" and key_name == "length":
                edge_keys[key_id] = key_name
            element.clear()
            root.clear()
        elif tag == "node":
            node_id = element.attrib.get("id")
            if node_id is None:
                element.clear()
                root.clear()
                continue
            attrs: dict[str, float] = {}
            for child in element:
                if _graphml_local_name(child.tag) != "data":
                    continue
                name = node_keys.get(child.attrib.get("key", ""))
                if name not in {"x", "y"} or child.text is None:
                    continue
                try:
                    attrs[name] = float(child.text)
                except ValueError:
                    continue
            if "x" in attrs and "y" in attrs:
                graph.add_node(node_id, **attrs)
            element.clear()
            root.clear()
        elif tag == "edge":
            source = element.attrib.get("source")
            target = element.attrib.get("target")
            if source is None or target is None:
                element.clear()
                root.clear()
                continue
            length_m = _edge_length_from_graphml(element, edge_keys)
            if length_m is None and source in graph and target in graph:
                length_m = haversine_distance_m(node_coordinate(graph, source), node_coordinate(graph, target))
            if length_m is None:
                element.clear()
                root.clear()
                continue
            edge_key = element.attrib.get("id")
            if edge_key is None:
                graph.add_edge(source, target, length=length_m)
            else:
                graph.add_edge(source, target, key=edge_key, length=length_m)
            element.clear()
            root.clear()

    graph.graph["source"] = f"graphml:{path.name}"
    graph.graph["sampling_loader"] = "minimal_graphml"
    return graph


def _edge_length_from_graphml(element: Any, edge_keys: dict[str, str]) -> float | None:
    for child in element:
        if _graphml_local_name(child.tag) != "data":
            continue
        if edge_keys.get(child.attrib.get("key", "")) != "length" or child.text is None:
            continue
        try:
            return float(child.text)
        except ValueError:
            return None
    return None


def _graphml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def largest_relevant_component(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Restrict a graph to its largest weakly connected component."""

    if graph.is_directed():
        components = list(nx.weakly_connected_components(graph))
    else:
        components = list(nx.connected_components(graph))
    if not components:
        raise ValueError("Graph contains no connected components")
    largest = max(components, key=len)
    subgraph = graph.subgraph(largest).copy()
    subgraph.graph.update(graph.graph)
    subgraph.graph["component_restriction"] = "largest"
    subgraph.graph["component_node_count"] = len(largest)
    return nx.MultiDiGraph(subgraph)


def node_coordinate(graph: nx.Graph, node: Any) -> Coordinate:
    """Return a node coordinate as ``(lat, lon)``."""

    data = graph.nodes[node]
    return float(data["y"]), float(data["x"])


def nodes_inside_raster_bounds(
    graph: nx.Graph,
    raster_paths: Sequence[str | Path],
    *,
    require_values: bool = True,
) -> list[Any]:
    """Return graph nodes covered by all requested rasters."""

    if not raster_paths:
        return [node for node, data in graph.nodes(data=True) if "x" in data and "y" in data]

    import rasterio
    from rasterio.warp import transform

    raster_info = []
    for raster_path in raster_paths:
        path = Path(raster_path)
        if not path.exists():
            raise FileNotFoundError(f"Raster path does not exist: {path}")
        dataset = rasterio.open(path)
        raster_info.append(dataset)

    try:
        covered: list[tuple[Any, float, float]] = [
            (node, float(data["y"]), float(data["x"]))
            for node, data in graph.nodes(data=True)
            if "x" in data and "y" in data
        ]
        for dataset in raster_info:
            if not covered:
                break
            x_values = [lon for _node, _lat, lon in covered]
            y_values = [lat for _node, lat, _lon in covered]
            if dataset.crs and str(dataset.crs).upper() not in {"EPSG:4326", "OGC:CRS84"}:
                x_values, y_values = transform("EPSG:4326", dataset.crs, x_values, y_values)

            in_bounds: list[tuple[Any, float, float, float, float]] = []
            for (node, lat, lon), x, y in zip(covered, x_values, y_values):
                if dataset.bounds.left <= x <= dataset.bounds.right and dataset.bounds.bottom <= y <= dataset.bounds.top:
                    in_bounds.append((node, lat, lon, x, y))

            if require_values:
                next_covered: list[tuple[Any, float, float]] = []
                points = [(x, y) for _node, _lat, _lon, x, y in in_bounds]
                for entry, sample in zip(in_bounds, dataset.sample(points)):
                    node, lat, lon, _x, _y = entry
                    if _sample_is_valid(dataset, sample):
                        next_covered.append((node, lat, lon))
                covered = next_covered
            else:
                covered = [(node, lat, lon) for node, lat, lon, _x, _y in in_bounds]
        return [node for node, _lat, _lon in covered]
    finally:
        for dataset in raster_info:
            dataset.close()


def _dataset_has_valid_value(dataset: Any, x: float, y: float) -> bool:
    """Return whether an already-open raster has a finite, non-nodata sample."""

    for sample in dataset.sample([(x, y)]):
        return _sample_is_valid(dataset, sample)
    return False


def _sample_is_valid(dataset: Any, sample: Sequence[Any]) -> bool:
    if len(sample) == 0:
        return False
    try:
        value = float(sample[0])
    except (TypeError, ValueError):
        return False
    if dataset.nodata is not None and value == float(dataset.nodata):
        return False
    return math.isfinite(value)


def generate_candidate_pairs(nodes: Sequence[Any], pair_count: int, *, seed: int) -> list[tuple[Any, Any]]:
    """Generate deterministic raw node pairs before shortest-path filtering."""

    if len(nodes) < 2:
        raise ValueError("At least two covered nodes are required for OD sampling")
    rng = random.Random(seed)
    pairs: list[tuple[Any, Any]] = []
    attempts = max(pair_count * 10, 100)
    for _idx in range(attempts):
        origin = rng.choice(nodes)
        destination = rng.choice(nodes)
        if origin != destination:
            pairs.append((origin, destination))
        if len(pairs) >= pair_count:
            break
    return pairs


def filter_pairs_by_shortest_distance(
    graph: nx.Graph,
    candidate_pairs: Iterable[tuple[Any, Any]],
    *,
    min_distance_m: float,
    max_distance_m: float,
    limit: int | None = None,
) -> list[ODPair]:
    """Keep OD pairs whose network shortest path is within the requested range."""

    kept: list[ODPair] = []
    seen: set[tuple[str, str]] = set()
    for origin, destination in candidate_pairs:
        key = (str(origin), str(destination))
        if key in seen:
            continue
        seen.add(key)
        try:
            distance_m = float(nx.shortest_path_length(graph, origin, destination, weight="length"))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        if not (min_distance_m <= distance_m <= max_distance_m):
            continue
        origin_lat, origin_lon = node_coordinate(graph, origin)
        destination_lat, destination_lon = node_coordinate(graph, destination)
        kept.append(
            ODPair(
                pair_id=f"od_{len(kept):05d}",
                origin_node=origin,
                destination_node=destination,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                destination_lat=destination_lat,
                destination_lon=destination_lon,
                baseline_shortest_distance_m=distance_m,
                component_id=0,
            )
        )
        if limit is not None and len(kept) >= limit:
            break
    return kept


def generate_od_pairs(
    graph: nx.MultiDiGraph,
    raster_paths: Sequence[str | Path],
    *,
    pair_count: int,
    seed: int,
    min_distance_m: float,
    max_distance_m: float,
    max_attempts: int | None = None,
) -> list[ODPair]:
    """Generate reproducible OD pairs inside graph and raster coverage."""

    component = largest_relevant_component(graph)
    nodes = nodes_inside_raster_bounds(component, raster_paths, require_values=True)
    if len(nodes) < 2:
        raise RuntimeError(
            "Could not generate OD pairs because fewer than two graph nodes have valid coverage "
            "in all configured rasters. Check raster bounds, CRS, NoData values, and graph extent."
        )
    attempts = max_attempts or max(pair_count * 500, 5_000)
    rng = random.Random(seed)
    candidates = ((rng.choice(nodes), rng.choice(nodes)) for _idx in range(attempts))
    pairs = filter_pairs_by_shortest_distance(
        component,
        ((origin, destination) for origin, destination in candidates if origin != destination),
        min_distance_m=min_distance_m,
        max_distance_m=max_distance_m,
        limit=pair_count,
    )
    if len(pairs) < pair_count:
        raise RuntimeError(
            "Could not generate enough OD pairs. "
            f"Requested {pair_count}, found {len(pairs)} after {attempts} attempts. "
            "Check raster coverage, graph connectivity, and min/max distance settings."
        )
    return pairs
