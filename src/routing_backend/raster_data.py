"""Real raster discovery and sampling helpers."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import math
import re
from typing import Iterable

from routing_backend.microclimate_model import Coordinate


def project_root() -> Path:
    """Return the repository root inferred from this package location."""

    return Path(__file__).resolve().parents[2]


def default_data_dir() -> Path:
    """Return the default project data directory."""

    return project_root() / "data"


def _parse_raster_timestamp(path: Path) -> tuple[str | None, int | None]:
    match = re.search(r"_(\d{4}-\d{2}-\d{2})_(\d{2})", path.stem)
    if not match:
        match = re.search(r"_(\d{2})$", path.stem)
    if not match:
        return None, None
    if len(match.groups()) == 2:
        return match.group(1), int(match.group(2))
    return None, int(match.group(1))


def raster_timestamp(path: Path | None) -> datetime | None:
    """Return the timestamp encoded in a dated raster filename."""

    if path is None:
        return None
    raster_date, raster_hour = _parse_raster_timestamp(path)
    if raster_date is None or raster_hour is None:
        return None
    try:
        return datetime.fromisoformat(f"{raster_date}T{raster_hour:02d}:00:00")
    except ValueError:
        return None


def find_time_raster(
    data_dir: Path,
    prefix: str,
    departure_time: datetime | float | int | None,
) -> Path | None:
    """Find the best raster matching a prefix and requested time."""

    search_dirs = [
        data_dir / "processed" / "solweig_outputs",
        data_dir / "processed" / "rasters",
    ]
    candidates: list[Path] = []
    for directory in search_dirs:
        if directory.exists():
            candidates.extend(sorted(directory.glob(f"{prefix}_*.tif")))
            candidates.extend(sorted(directory.glob(f"{prefix}_*.tiff")))

    if not candidates:
        return None

    requested_date: str | None = None
    requested_hour: int | None = None
    if isinstance(departure_time, datetime):
        requested_date = departure_time.date().isoformat()
        requested_hour = departure_time.hour
    elif departure_time is not None:
        requested_hour = int(float(departure_time)) % 24

    def score(path: Path) -> tuple[int, int, int, str]:
        raster_date, raster_hour = _parse_raster_timestamp(path)
        date_score = 0 if requested_date and raster_date == requested_date else 1
        try:
            date_ordinal = date.fromisoformat(raster_date).toordinal() if raster_date else 0
        except ValueError:
            date_ordinal = 0
        if requested_hour is None or raster_hour is None:
            hour_score = 99
        else:
            direct = abs(raster_hour - requested_hour)
            hour_score = min(direct, 24 - direct)
        # Exact dates win. When no exact date exists, prefer the newest dated
        # dataset before choosing the closest available hour.
        return date_score, -date_ordinal, hour_score, str(path)

    return min(candidates, key=score)


def sample_raster_values(raster_path: Path, points: Iterable[Coordinate]) -> list[float]:
    """Sample a GeoTIFF at ``(lat, lon)`` points.

    Returns only finite, non-nodata samples.
    """

    try:
        import rasterio
        from rasterio.warp import transform
    except ImportError as exc:
        raise RuntimeError("rasterio is required to sample real rasters") from exc

    point_list = list(points)
    if not point_list:
        return []

    with rasterio.open(raster_path) as dataset:
        xs = [lon for _lat, lon in point_list]
        ys = [lat for lat, _lon in point_list]
        if dataset.crs and str(dataset.crs).upper() not in {"EPSG:4326", "OGC:CRS84"}:
            xs, ys = transform("EPSG:4326", dataset.crs, xs, ys)

        in_bounds = [
            (x, y)
            for x, y in zip(xs, ys)
            if dataset.bounds.left <= x < dataset.bounds.right
            and dataset.bounds.bottom < y <= dataset.bounds.top
        ]
        values: list[float] = []
        nodata = dataset.nodata
        for sample in dataset.sample(in_bounds):
            if len(sample) == 0:
                continue
            value = float(sample[0])
            if nodata is not None and value == float(nodata):
                continue
            if math.isfinite(value):
                values.append(value)
        return values


def first_existing(paths: Iterable[Path]) -> Path | None:
    """Return the first existing path from an iterable."""

    for path in paths:
        if path.exists():
            return path
    return None


def default_dem_path(data_dir: Path | None = None) -> Path | None:
    """Return the preferred DEM path if the bundle contains one."""

    root = data_dir or default_data_dir()
    return first_existing(
        [
            root / "processed" / "rasters" / "dem_1m.tif",
            root / "raw" / "lidar" / "dem_2022_tiles" / "DTM_2022_1m.tif",
        ]
    )
