from pathlib import Path

import pytest

from routing_backend.experiment_config import ExperimentConfig, ExperimentConfigError


def _payload() -> dict:
    return {
        "study_name": "unit",
        "city": "Washington, District of Columbia, USA",
        "mode": "walk",
        "departure_time": "2026-06-19T14:00:00",
        "graph_path": "graph.graphml",
        "utci_raster_path": "utci.tif",
        "shadow_raster_path": "shadow.tif",
        "dem_raster_path": "dem.tif",
        "canopy_raster_paths": ["canopy.tif"],
        "traffic_geojson_path": "traffic.geojson",
        "output_dir": "results/unit",
        "random_seed": 7,
        "od_pair_count": 10,
        "min_shortest_distance_m": 100,
        "max_shortest_distance_m": 1000,
        "detour_ratios": [0, 0.1],
        "comfort_threshold_c": 26.0,
        "sample_spacing_m": 20.0,
        "route_search_seconds": 1.5,
        "route_search_expansions": 20000,
        "route_search_labels_per_node": 8,
    }


def test_experiment_config_loads_paths_relative_to_base(tmp_path: Path) -> None:
    config = ExperimentConfig.from_mapping(_payload(), base_dir=tmp_path)

    assert config.study_name == "unit"
    assert config.departure_time.hour == 14
    assert config.graph_path == (tmp_path / "graph.graphml").resolve()
    assert config.detour_ratios == (0.0, 0.1)


def test_experiment_config_missing_required_field_fails(tmp_path: Path) -> None:
    payload = _payload()
    payload.pop("graph_path")

    with pytest.raises(ExperimentConfigError, match="graph_path"):
        ExperimentConfig.from_mapping(payload, base_dir=tmp_path)


def test_experiment_config_requires_canopy_path(tmp_path: Path) -> None:
    payload = _payload()
    payload["canopy_raster_paths"] = []

    with pytest.raises(ExperimentConfigError, match="canopy_raster_paths"):
        ExperimentConfig.from_mapping(payload, base_dir=tmp_path)
