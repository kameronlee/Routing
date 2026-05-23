"""Join staged real geospatial layers onto routing graph edges."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from numbers import Integral
from pathlib import Path
from typing import Any, Iterable, Sequence

from shapely.geometry import LineString, Point, shape
from shapely.strtree import STRtree

from routing_backend.microclimate_model import Coordinate, densify_geometry
from routing_backend.raster_data import default_data_dir, find_time_raster


class RealDataMissingError(RuntimeError):
    """Raised when strict real-data routing lacks a required input layer."""


@dataclass(frozen=True)
class RealFeaturePaths:
    """Paths to real-data layers used by edge feature extraction."""

    utci_raster: Path
    canopy_height_rasters: tuple[Path, ...]
    canopy_class_rasters: tuple[Path, ...]
    landcover_rasters: tuple[Path, ...]
    traffic_geojson: Path


def _existing(paths: Iterable[Path]) -> tuple[Path, ...]:
    return tuple(path for path in paths if path.exists())


def discover_real_feature_paths(data_dir: Path, departure_time: object) -> RealFeaturePaths:
    """Discover required real-data layers for strict routing."""

    utci_raster = find_time_raster(data_dir, "utci", departure_time)
    canopy_height_rasters = _existing(
        [
            data_dir / "processed" / "rasters" / "canopy_height_1m.tif",
            data_dir / "processed" / "solweig_inputs" / "trees_cdsm_1m.tif",
        ]
    )
    canopy_class_rasters = _existing(
        [
            data_dir / "processed" / "rasters" / "canopy_1m.tif",
            data_dir / "processed" / "rasters" / "canopy_1m_center_tile.tif",
            data_dir / "processed" / "solweig_inputs" / "trees_cdsm_1m_center_tile.tif",
            data_dir / "raw" / "canopy" / "urban_tree_canopy_2020_center_tile.tif",
        ]
    )
    landcover_rasters = _existing(
        [
            data_dir / "processed" / "rasters" / "landcover_1m.tif",
            data_dir / "processed" / "rasters" / "landcover_1m_center_tile.tif",
            data_dir / "processed" / "solweig_inputs" / "landcover_1m.tif",
            data_dir / "processed" / "solweig_inputs" / "landcover_1m_center_tile.tif",
            data_dir / "raw" / "landcover" / "dc_generalized_landcover_2020_center_tile.tif",
        ]
    )
    traffic_geojson = data_dir / "raw" / "traffic_noise" / "ddot_traffic_volume_2023.geojson"

    missing: list[str] = []
    if utci_raster is None:
        missing.append("UTCI raster in data/processed/solweig_outputs/utci_YYYY-MM-DD_HH.tif")
    if not canopy_height_rasters and not canopy_class_rasters:
        missing.append("tree canopy or canopy-height raster")
    if not traffic_geojson.exists():
        missing.append("DDOT traffic volume GeoJSON")
    if missing:
        raise RealDataMissingError("Missing required real-data layer(s): " + "; ".join(missing))

    return RealFeaturePaths(
        utci_raster=utci_raster,
        canopy_height_rasters=canopy_height_rasters,
        canopy_class_rasters=canopy_class_rasters,
        landcover_rasters=landcover_rasters,
        traffic_geojson=traffic_geojson,
    )


class RasterCollection:
    """Small collection of open rasters sampled as one logical layer."""

    def __init__(self, paths: Sequence[Path]) -> None:
        try:
            import rasterio
            from rasterio.warp import transform
        except ImportError as exc:  # pragma: no cover - environment guard
            raise RealDataMissingError("rasterio is required for real raster sampling") from exc

        self._rasterio = rasterio
        self._transform = transform
        self.datasets = [rasterio.open(path) for path in paths]

    def close(self) -> None:
        """Close all open raster handles."""

        for dataset in self.datasets:
            dataset.close()

    def sample(self, points: Sequence[Coordinate]) -> list[float]:
        """Sample all covered points and return finite non-nodata values."""

        values: list[float] = []
        if not points:
            return values

        remaining = list(points)
        for dataset in self.datasets:
            if not remaining:
                break
            xs = [lon for _lat, lon in remaining]
            ys = [lat for lat, _lon in remaining]
            if dataset.crs and str(dataset.crs).upper() not in {"EPSG:4326", "OGC:CRS84"}:
                xs, ys = self._transform("EPSG:4326", dataset.crs, xs, ys)

            covered: list[tuple[Coordinate, float, float]] = []
            still_remaining: list[Coordinate] = []
            left, bottom, right, top = dataset.bounds
            for coordinate, x, y in zip(remaining, xs, ys):
                if left <= x <= right and bottom <= y <= top:
                    covered.append((coordinate, x, y))
                else:
                    still_remaining.append(coordinate)

            nodata = dataset.nodata
            for _coordinate, x, y in covered:
                sample = next(dataset.sample([(x, y)]))
                if len(sample) == 0:
                    continue
                value = float(sample[0])
                if nodata is not None and value == float(nodata):
                    continue
                if math.isfinite(value):
                    values.append(value)
            remaining = still_remaining
        return values


class TrafficIndex:
    """Nearest-neighbor index over DDOT traffic volume segments."""

    def __init__(self, geojson_path: Path) -> None:
        payload = json.loads(geojson_path.read_text(encoding="utf-8"))
        geometries = []
        aadts = []
        for feature in payload.get("features", []):
            geometry_payload = feature.get("geometry")
            if not geometry_payload:
                continue
            geometry = shape(geometry_payload)
            if geometry.is_empty:
                continue
            aadt = feature.get("properties", {}).get("AADT")
            if aadt is None:
                continue
            geometries.append(geometry)
            aadts.append(float(aadt))

        if not geometries:
            raise RealDataMissingError(f"No usable DDOT AADT records in {geojson_path}")

        self.geometries = geometries
        self.aadts = aadts
        self.max_aadt = max(aadts)
        self.tree = STRtree(geometries)

    def nearest_score(self, points: Sequence[Coordinate]) -> tuple[float, float, float]:
        """Return normalized traffic noise score, nearest AADT and angular distance."""

        if not points:
            raise RealDataMissingError("Cannot join traffic to an empty edge geometry")

        line = LineString([(lon, lat) for lat, lon in points])
        midpoint = line.interpolate(0.5, normalized=True)
        nearest_index = self.tree.nearest(midpoint)
        if isinstance(nearest_index, Integral):
            index = int(nearest_index)
        else:  # Shapely < 2 returns the geometry itself.
            index = self.geometries.index(nearest_index)
        nearest_geometry = self.geometries[index]
        distance_degrees = midpoint.distance(nearest_geometry)
        aadt = self.aadts[index]
        score = math.log10(aadt + 1.0) / math.log10(self.max_aadt + 1.0)
        return max(0.0, min(1.0, score)), aadt, distance_degrees


class RealFeatureContext:
    """Context object that joins real rasters/vectors onto edges."""

    def __init__(self, paths: RealFeaturePaths) -> None:
        self.paths = paths
        self.canopy_height = RasterCollection(paths.canopy_height_rasters)
        self.canopy_class = RasterCollection(paths.canopy_class_rasters)
        self.landcover = RasterCollection(paths.landcover_rasters)
        self.traffic = TrafficIndex(paths.traffic_geojson)

    @classmethod
    def from_data_dir(cls, data_dir: Path | None, departure_time: object) -> "RealFeatureContext":
        """Build a context from a data directory, requiring all real layers."""

        paths = discover_real_feature_paths(data_dir or default_data_dir(), departure_time)
        return cls(paths)

    def close(self) -> None:
        """Release raster handles."""

        self.canopy_height.close()
        self.canopy_class.close()
        self.landcover.close()

    @staticmethod
    def _summarize_canopy_height(values: Sequence[float]) -> dict[str, float]:
        """Summarize LiDAR canopy-height samples in meters."""

        if not values:
            return {
                "tree_canopy_fraction": 0.0,
                "greenery_index": 0.0,
                "canopy_height_mean_m": 0.0,
                "canopy_height_max_m": 0.0,
                "canopy_height_score": 0.0,
            }
        mean_height = sum(values) / len(values)
        max_height = max(values)
        return {
            "tree_canopy_fraction": sum(1 for value in values if value >= 2.0) / len(values),
            "greenery_index": sum(1 for value in values if value >= 0.5) / len(values),
            "canopy_height_mean_m": mean_height,
            "canopy_height_max_m": max_height,
            "canopy_height_score": max(0.0, min(1.0, mean_height / 12.0)),
        }

    @staticmethod
    def _summarize_categorical_canopy(values: Sequence[float]) -> dict[str, float]:
        """Summarize DC categorical tree-canopy raster samples."""

        if not values:
            return {
                "tree_canopy_fraction": 0.0,
                "greenery_index": 0.0,
                "canopy_height_mean_m": 0.0,
                "canopy_height_max_m": 0.0,
                "canopy_height_score": 0.0,
            }
        rounded = [int(round(value)) for value in values]
        return {
            "tree_canopy_fraction": sum(1 for value in rounded if value == 101) / len(rounded),
            "greenery_index": sum(1 for value in rounded if value in {101, 111, 121}) / len(rounded),
            "canopy_height_mean_m": 0.0,
            "canopy_height_max_m": 0.0,
            "canopy_height_score": 0.0,
        }

    def edge_attributes(
        self,
        points: Sequence[Coordinate],
        _edge_data: dict[str, Any],
        _length_m: float,
    ) -> dict[str, float]:
        """Compute real edge-level perceptual/noise attributes."""

        samples = densify_geometry(points, spacing_m=20.0)
        canopy_height_values = self.canopy_height.sample(samples)
        canopy_class_values = self.canopy_class.sample(samples)
        landcover_values = self.landcover.sample(samples)

        if canopy_height_values:
            canopy_summary = self._summarize_canopy_height(canopy_height_values)
        elif canopy_class_values:
            canopy_summary = self._summarize_categorical_canopy(canopy_class_values)
        else:
            raise RealDataMissingError("No canopy or canopy-height raster coverage for an edge in this route corridor")

        if landcover_values:
            rounded_landcover = [int(round(value)) for value in landcover_values]
            landcover_green_fraction = sum(1 for value in rounded_landcover if value in {1, 10}) / len(
                rounded_landcover
            )
            water_fraction = sum(1 for value in rounded_landcover if value == 30) / len(rounded_landcover)
        else:
            landcover_green_fraction = 0.0
            water_fraction = 0.0

        canopy_fraction = canopy_summary["tree_canopy_fraction"]
        greenery_index = max(canopy_summary["greenery_index"], landcover_green_fraction)
        scenic_score = max(
            0.0,
            min(
                1.0,
                0.60 * canopy_fraction
                + 0.25 * canopy_summary["canopy_height_score"]
                + 0.10 * greenery_index
                + 0.05 * water_fraction,
            ),
        )
        noise_score, traffic_aadt, traffic_distance_degrees = self.traffic.nearest_score(points)

        return {
            "tree_canopy_fraction": canopy_fraction,
            "greenery_index": greenery_index,
            "canopy_height_mean_m": canopy_summary["canopy_height_mean_m"],
            "canopy_height_max_m": canopy_summary["canopy_height_max_m"],
            "landcover_green_fraction": landcover_green_fraction,
            "water_fraction": water_fraction,
            "scenic_score": scenic_score,
            "noise_score": noise_score,
            "traffic_aadt": traffic_aadt,
            "traffic_join_distance_degrees": traffic_distance_degrees,
            "feature_uncertainty": 0.0,
        }
