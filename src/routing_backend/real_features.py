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

from routing_backend.microclimate_model import Coordinate, densify_geometry, offset_coordinate
from routing_backend.raster_data import default_data_dir, find_time_raster


class RealDataMissingError(RuntimeError):
    """Raised when strict real-data routing lacks a required input layer."""


_DISABLABLE_LAYERS = {"canopy", "landcover", "building_height"}


@dataclass(frozen=True)
class RealFeaturePaths:
    """Paths to real-data layers used by edge feature extraction."""

    utci_raster: Path
    shadow_raster: Path | None
    canopy_height_rasters: tuple[Path, ...]
    canopy_class_rasters: tuple[Path, ...]
    landcover_rasters: tuple[Path, ...]
    traffic_geojson: Path
    building_height_rasters: tuple[Path, ...] = ()


def _existing(paths: Iterable[Path]) -> tuple[Path, ...]:
    return tuple(path for path in paths if path.exists())


def discover_real_feature_paths(data_dir: Path, departure_time: object) -> RealFeaturePaths:
    """Discover required real-data layers for strict routing."""

    utci_raster = find_time_raster(data_dir, "utci", departure_time)
    shadow_raster = find_time_raster(data_dir, "shadow", departure_time)
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
    building_height_rasters = _existing(
        [
            data_dir / "processed" / "rasters" / "building_height_1m.tif",
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
        shadow_raster=shadow_raster,
        canopy_height_rasters=canopy_height_rasters,
        canopy_class_rasters=canopy_class_rasters,
        landcover_rasters=landcover_rasters,
        traffic_geojson=traffic_geojson,
        building_height_rasters=building_height_rasters,
    )


def _edge_bearing_degrees(points: Sequence[Coordinate]) -> float | None:
    if len(points) < 2:
        return None
    start = points[0]
    end = points[-1]
    lat1, lon1 = map(math.radians, start)
    lat2, lon2 = map(math.radians, end)
    delta_lon = lon2 - lon1
    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _first_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return _first_number(value[0]) if value else None
    if isinstance(value, str):
        text = value.strip().lower()
        for separator in (";", ","):
            text = text.split(separator, 1)[0]
        text = text.replace("meters", "").replace("meter", "").replace("m", "").strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
    return number if number > 0.0 else None


def _street_width_m(edge_data: dict[str, Any]) -> float:
    width = (
        _first_number(edge_data.get("street_width_m"))
        or _first_number(edge_data.get("street_width"))
        or _first_number(edge_data.get("width"))
    )
    if width is not None:
        return width
    lanes = _first_number(edge_data.get("lanes"))
    if lanes is not None:
        return max(4.0, lanes * 3.2)
    return 10.0


def _lateral_sample_points(
    points: Sequence[Coordinate],
    edge_data: dict[str, Any],
    sample_spacing_m: float,
) -> list[Coordinate]:
    samples = densify_geometry(points, spacing_m=sample_spacing_m)
    bearing = _edge_bearing_degrees(points)
    if bearing is None:
        return samples

    width_m = _street_width_m(edge_data)
    offsets = (-width_m, -width_m / 2.0, width_m / 2.0, width_m)
    bearing_rad = math.radians(bearing)
    left_north = -math.sin(bearing_rad)
    left_east = math.cos(bearing_rad)
    lateral_samples = list(samples)
    for sample in samples:
        for offset_m in offsets:
            lateral_samples.append(
                offset_coordinate(
                    sample,
                    north_m=left_north * offset_m,
                    east_m=left_east * offset_m,
                )
            )
    return lateral_samples


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

        return self.sample_groups([points])[0] if points else []

    def sample_groups(self, point_groups: Sequence[Sequence[Coordinate]]) -> list[list[float]]:
        """Sample grouped points while preserving group membership."""

        values: list[list[float]] = [[] for _group in point_groups]
        remaining: list[tuple[int, Coordinate]] = [
            (group_index, coordinate)
            for group_index, points in enumerate(point_groups)
            for coordinate in points
        ]
        for dataset in self.datasets:
            if not remaining:
                break
            xs = [lon for _group_index, (_lat, lon) in remaining]
            ys = [lat for _group_index, (lat, _lon) in remaining]
            if dataset.crs and str(dataset.crs).upper() not in {"EPSG:4326", "OGC:CRS84"}:
                xs, ys = self._transform("EPSG:4326", dataset.crs, xs, ys)

            covered: list[tuple[int, float, float]] = []
            still_remaining: list[tuple[int, Coordinate]] = []
            left, bottom, right, top = dataset.bounds
            for (group_index, coordinate), x, y in zip(remaining, xs, ys):
                if left <= x <= right and bottom <= y <= top:
                    covered.append((group_index, x, y))
                else:
                    still_remaining.append((group_index, coordinate))

            nodata = dataset.nodata
            sample_points = [(x, y) for _group_index, x, y in covered]
            for (group_index, _x, _y), sample in zip(covered, dataset.sample(sample_points)):
                if len(sample) == 0:
                    continue
                try:
                    value = float(sample[0])
                except (TypeError, ValueError):
                    continue
                if nodata is not None and value == float(nodata):
                    continue
                if math.isfinite(value):
                    values[group_index].append(value)
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

    def __init__(self, paths: RealFeaturePaths, *, disabled_layers: Iterable[str] = ()) -> None:
        disabled = frozenset(disabled_layers)
        unknown = sorted(disabled - _DISABLABLE_LAYERS)
        if unknown:
            raise ValueError("Unknown real-feature layer(s): " + ", ".join(unknown))
        self.paths = paths
        self.disabled_layers = disabled
        self.utci = RasterCollection((paths.utci_raster,))
        self.shadow = RasterCollection((paths.shadow_raster,)) if paths.shadow_raster is not None else None
        self.canopy_height = (
            RasterCollection(())
            if self._is_disabled("canopy")
            else RasterCollection(paths.canopy_height_rasters)
        )
        self.canopy_class = (
            RasterCollection(())
            if self._is_disabled("canopy")
            else RasterCollection(paths.canopy_class_rasters)
        )
        self.landcover = (
            RasterCollection(())
            if self._is_disabled("landcover")
            else RasterCollection(paths.landcover_rasters)
        )
        self.building_height = (
            RasterCollection(())
            if self._is_disabled("building_height")
            else RasterCollection(paths.building_height_rasters)
        )
        self.traffic = TrafficIndex(paths.traffic_geojson)

    @classmethod
    def from_data_dir(cls, data_dir: Path | None, departure_time: object) -> "RealFeatureContext":
        """Build a context from a data directory, requiring all real layers."""

        paths = discover_real_feature_paths(data_dir or default_data_dir(), departure_time)
        return cls(paths)

    def _is_disabled(self, layer: str) -> bool:
        return layer in self.disabled_layers

    def close(self) -> None:
        """Release raster handles."""

        self.utci.close()
        if self.shadow is not None:
            self.shadow.close()
        self.canopy_height.close()
        self.canopy_class.close()
        self.landcover.close()
        self.building_height.close()

    def utci_values(self, points: Sequence[Coordinate]) -> list[float]:
        """Sample UTCI from the already-open SOLWEIG raster."""

        return self.utci.sample(points)

    def utci_values_many(self, point_groups: Sequence[Sequence[Coordinate]]) -> list[list[float]]:
        """Sample UTCI for many grouped edge point sequences."""

        return self.utci.sample_groups(point_groups)

    def shadow_values(self, points: Sequence[Coordinate]) -> list[float]:
        """Sample SOLWEIG shadow values when direct shadow output is available."""

        return self.shadow.sample(points) if self.shadow is not None else []

    def shadow_values_many(self, point_groups: Sequence[Sequence[Coordinate]]) -> list[list[float]]:
        """Sample SOLWEIG shadow values for many grouped edge point sequences."""

        if self.shadow is None:
            return [[] for _group in point_groups]
        return self.shadow.sample_groups(point_groups)

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

    @staticmethod
    def _summarize_building_height(values: Sequence[float]) -> dict[str, float]:
        """Summarize sampled building heights adjacent to an edge."""

        occupied = [value for value in values if value >= 2.0]
        if not occupied:
            return {
                "building_fraction": 0.0,
                "building_height_mean_m": 0.0,
                "building_height_max_m": 0.0,
            }
        return {
            "building_fraction": len(occupied) / len(values),
            "building_height_mean_m": sum(occupied) / len(occupied),
            "building_height_max_m": max(occupied),
        }

    def edge_attributes(
        self,
        points: Sequence[Coordinate],
        edge_data: dict[str, Any],
        _length_m: float,
    ) -> dict[str, float]:
        """Compute real edge-level perceptual/noise attributes."""

        samples = densify_geometry(points, spacing_m=20.0)
        canopy_height_values = [] if self._is_disabled("canopy") else self.canopy_height.sample(samples)
        canopy_class_values = [] if self._is_disabled("canopy") else self.canopy_class.sample(samples)
        landcover_values = [] if self._is_disabled("landcover") else self.landcover.sample(samples)
        building_height_values = (
            []
            if self._is_disabled("building_height")
            else self.building_height.sample(_lateral_sample_points(points, edge_data, 20.0))
        )

        if self._is_disabled("canopy"):
            canopy_summary = self._summarize_canopy_height([])
        elif canopy_height_values:
            canopy_summary = self._summarize_canopy_height(canopy_height_values)
        elif canopy_class_values:
            canopy_summary = self._summarize_categorical_canopy(canopy_class_values)
        else:
            raise RealDataMissingError(
                "No canopy or canopy-height raster coverage for an edge in this route corridor"
            )

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
        building_summary = self._summarize_building_height(building_height_values)

        return {
            "tree_canopy_fraction": canopy_fraction,
            "greenery_index": greenery_index,
            "canopy_height_mean_m": canopy_summary["canopy_height_mean_m"],
            "canopy_height_max_m": canopy_summary["canopy_height_max_m"],
            "building_fraction": building_summary["building_fraction"],
            "building_height_mean_m": building_summary["building_height_mean_m"],
            "building_height_max_m": building_summary["building_height_max_m"],
            "landcover_green_fraction": landcover_green_fraction,
            "water_fraction": water_fraction,
            "scenic_score": scenic_score,
            "noise_score": noise_score,
            "traffic_aadt": traffic_aadt,
            "traffic_join_distance_degrees": traffic_distance_degrees,
            "feature_uncertainty": 0.0,
        }

    def edge_attributes_many(
        self,
        edge_groups: Sequence[tuple[Sequence[Coordinate], dict[str, Any], float]],
        sample_spacing_m: float = 20.0,
    ) -> list[dict[str, float]]:
        """Compute real edge-level attributes for many edges with batched raster reads."""

        sample_groups = [
            densify_geometry(points, spacing_m=sample_spacing_m)
            for points, _data, _length in edge_groups
        ]
        building_sample_groups = [
            _lateral_sample_points(points, edge_data, sample_spacing_m)
            for points, edge_data, _length in edge_groups
        ]
        canopy_height_groups = (
            [[] for _group in sample_groups]
            if self._is_disabled("canopy")
            else self.canopy_height.sample_groups(sample_groups)
        )
        canopy_class_groups = (
            [[] for _group in sample_groups]
            if self._is_disabled("canopy")
            else self.canopy_class.sample_groups(sample_groups)
        )
        landcover_groups = (
            [[] for _group in sample_groups]
            if self._is_disabled("landcover")
            else self.landcover.sample_groups(sample_groups)
        )
        building_height_groups = (
            [[] for _group in building_sample_groups]
            if self._is_disabled("building_height")
            else self.building_height.sample_groups(building_sample_groups)
        )

        attributes: list[dict[str, float]] = []
        for (
            (points, _edge_data, _length_m),
            canopy_height_values,
            canopy_class_values,
            landcover_values,
            building_height_values,
        ) in zip(
            edge_groups,
            canopy_height_groups,
            canopy_class_groups,
            landcover_groups,
            building_height_groups,
        ):
            if self._is_disabled("canopy"):
                canopy_summary = self._summarize_canopy_height([])
            elif canopy_height_values:
                canopy_summary = self._summarize_canopy_height(canopy_height_values)
            elif canopy_class_values:
                canopy_summary = self._summarize_categorical_canopy(canopy_class_values)
            else:
                raise RealDataMissingError(
                    "No canopy or canopy-height raster coverage for an edge in this route corridor"
                )

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
            building_summary = self._summarize_building_height(building_height_values)
            attributes.append(
                {
                    "tree_canopy_fraction": canopy_fraction,
                    "greenery_index": greenery_index,
                    "canopy_height_mean_m": canopy_summary["canopy_height_mean_m"],
                    "canopy_height_max_m": canopy_summary["canopy_height_max_m"],
                    "building_fraction": building_summary["building_fraction"],
                    "building_height_mean_m": building_summary["building_height_mean_m"],
                    "building_height_max_m": building_summary["building_height_max_m"],
                    "landcover_green_fraction": landcover_green_fraction,
                    "water_fraction": water_fraction,
                    "scenic_score": scenic_score,
                    "noise_score": noise_score,
                    "traffic_aadt": traffic_aadt,
                    "traffic_join_distance_degrees": traffic_distance_degrees,
                    "feature_uncertainty": 0.0,
                }
            )
        return attributes
