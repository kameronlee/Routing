"""Configuration loading for reproducible routing experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from routing_backend.raster_data import find_time_raster, project_root


class ExperimentConfigError(ValueError):
    """Raised when an experiment configuration is missing required values."""


_REQUIRED_FIELDS = {
    "study_name",
    "city",
    "mode",
    "departure_time",
    "graph_path",
    "utci_raster_path",
    "shadow_raster_path",
    "dem_raster_path",
    "canopy_raster_paths",
    "traffic_geojson_path",
    "output_dir",
    "random_seed",
    "od_pair_count",
    "min_shortest_distance_m",
    "max_shortest_distance_m",
    "detour_ratios",
    "comfort_threshold_c",
    "sample_spacing_m",
    "route_search_seconds",
    "route_search_expansions",
    "route_search_labels_per_node",
}


@dataclass(frozen=True)
class ExperimentConfig:
    """Validated configuration for one routing paper snapshot experiment."""

    study_name: str
    city: str
    mode: str
    departure_time: datetime
    graph_path: Path
    utci_raster_path: Path
    shadow_raster_path: Path
    dem_raster_path: Path
    canopy_raster_paths: tuple[Path, ...]
    traffic_geojson_path: Path
    output_dir: Path
    random_seed: int
    od_pair_count: int
    min_shortest_distance_m: float
    max_shortest_distance_m: float
    detour_ratios: tuple[float, ...]
    comfort_threshold_c: float
    sample_spacing_m: float
    route_search_seconds: float
    route_search_expansions: int
    route_search_labels_per_node: int
    landcover_raster_paths: tuple[Path, ...] = field(default_factory=tuple)
    building_height_raster_paths: tuple[Path, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any], *, base_dir: Path | None = None) -> "ExperimentConfig":
        """Build a config from a dictionary and validate required fields."""

        missing = sorted(field_name for field_name in _REQUIRED_FIELDS if field_name not in payload)
        if missing:
            raise ExperimentConfigError("Missing required experiment config field(s): " + ", ".join(missing))

        root = base_dir or project_root()

        def path_value(name: str) -> Path:
            return _resolve_path(payload[name], root)

        def path_tuple(name: str) -> tuple[Path, ...]:
            values = payload.get(name, [])
            if values is None:
                return ()
            if not isinstance(values, list):
                raise ExperimentConfigError(f"{name} must be a list of paths")
            return tuple(_resolve_path(value, root) for value in values)

        try:
            departure_time = datetime.fromisoformat(str(payload["departure_time"]))
        except ValueError as exc:
            raise ExperimentConfigError("departure_time must be ISO-8601, for example 2026-06-19T14:00:00") from exc

        detour_ratios = tuple(float(value) for value in payload["detour_ratios"])
        if not detour_ratios:
            raise ExperimentConfigError("detour_ratios must contain at least one value")
        if any(value < 0 for value in detour_ratios):
            raise ExperimentConfigError("detour_ratios must be non-negative")

        canopy_paths = path_tuple("canopy_raster_paths")
        if not canopy_paths:
            raise ExperimentConfigError("canopy_raster_paths must contain at least one real raster path")

        min_distance = float(payload["min_shortest_distance_m"])
        max_distance = float(payload["max_shortest_distance_m"])
        if min_distance <= 0 or max_distance <= 0 or min_distance > max_distance:
            raise ExperimentConfigError("min/max shortest-path distances must be positive and ordered")

        return cls(
            study_name=str(payload["study_name"]),
            city=str(payload["city"]),
            mode=str(payload["mode"]),
            departure_time=departure_time,
            graph_path=path_value("graph_path"),
            utci_raster_path=path_value("utci_raster_path"),
            shadow_raster_path=path_value("shadow_raster_path"),
            dem_raster_path=path_value("dem_raster_path"),
            canopy_raster_paths=canopy_paths,
            traffic_geojson_path=path_value("traffic_geojson_path"),
            output_dir=path_value("output_dir"),
            random_seed=int(payload["random_seed"]),
            od_pair_count=int(payload["od_pair_count"]),
            min_shortest_distance_m=min_distance,
            max_shortest_distance_m=max_distance,
            detour_ratios=detour_ratios,
            comfort_threshold_c=float(payload["comfort_threshold_c"]),
            sample_spacing_m=float(payload["sample_spacing_m"]),
            route_search_seconds=float(payload["route_search_seconds"]),
            route_search_expansions=int(payload["route_search_expansions"]),
            route_search_labels_per_node=int(payload["route_search_labels_per_node"]),
            landcover_raster_paths=path_tuple("landcover_raster_paths"),
            building_height_raster_paths=path_tuple("building_height_raster_paths"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "study_name": self.study_name,
            "city": self.city,
            "mode": self.mode,
            "departure_time": self.departure_time.isoformat(),
            "graph_path": str(self.graph_path),
            "utci_raster_path": str(self.utci_raster_path),
            "shadow_raster_path": str(self.shadow_raster_path),
            "dem_raster_path": str(self.dem_raster_path),
            "canopy_raster_paths": [str(path) for path in self.canopy_raster_paths],
            "traffic_geojson_path": str(self.traffic_geojson_path),
            "output_dir": str(self.output_dir),
            "random_seed": self.random_seed,
            "od_pair_count": self.od_pair_count,
            "min_shortest_distance_m": self.min_shortest_distance_m,
            "max_shortest_distance_m": self.max_shortest_distance_m,
            "detour_ratios": list(self.detour_ratios),
            "comfort_threshold_c": self.comfort_threshold_c,
            "sample_spacing_m": self.sample_spacing_m,
            "route_search_seconds": self.route_search_seconds,
            "route_search_expansions": self.route_search_expansions,
            "route_search_labels_per_node": self.route_search_labels_per_node,
            "landcover_raster_paths": [str(path) for path in self.landcover_raster_paths],
            "building_height_raster_paths": [str(path) for path in self.building_height_raster_paths],
        }

    def require_existing_inputs(self) -> None:
        """Fail clearly if the main real-data inputs are missing."""

        required_paths = {
            "graph_path": self.graph_path,
            "utci_raster_path": self.utci_raster_path,
            "shadow_raster_path": self.shadow_raster_path,
            "dem_raster_path": self.dem_raster_path,
            "traffic_geojson_path": self.traffic_geojson_path,
        }
        missing = [f"{name}={path}" for name, path in required_paths.items() if not path.exists()]
        missing.extend(f"canopy_raster_path={path}" for path in self.canopy_raster_paths if not path.exists())
        missing.extend(f"landcover_raster_path={path}" for path in self.landcover_raster_paths if not path.exists())
        missing.extend(
            f"building_height_raster_path={path}" for path in self.building_height_raster_paths if not path.exists()
        )
        if missing:
            raise FileNotFoundError(
                "Missing required real-data experiment input(s). Update the config or generate the data first: "
                + "; ".join(missing)
            )
        all_paths = [*required_paths.values(), *self.canopy_raster_paths,
                     *self.landcover_raster_paths, *self.building_height_raster_paths]
        for path in all_paths:
            with path.open("rb") as handle:
                if handle.read(80).startswith(b"version https://git-lfs.github.com/spec/v1"):
                    raise FileNotFoundError(
                        f"Input is a Git LFS pointer, not the downloaded data: {path}. "
                        "Restore the matching LFS object or use the complete Hopper data bundle."
                    )


def _resolve_path(value: Any, base_dir: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    """Load YAML or JSON experiment configuration from disk."""

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Experiment config not found: {config_path}")
    text = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() == ".json":
        payload = json.loads(text)
    else:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise ExperimentConfigError("PyYAML is required to load YAML config files") from exc
        payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ExperimentConfigError("Experiment config must be a mapping")
    return ExperimentConfig.from_mapping(payload, base_dir=project_root())


def discover_likely_snapshot_rasters(
    *,
    data_dir: Path | None = None,
    departure_time: datetime | None = None,
) -> dict[str, Path | None]:
    """Discover likely UTCI and direct-shadow rasters for config authoring."""

    root = data_dir or project_root() / "data"
    return {
        "utci_raster_path": find_time_raster(root, "utci", departure_time),
        "shadow_raster_path": find_time_raster(root, "shadow", departure_time),
    }
