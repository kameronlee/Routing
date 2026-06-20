"""Micro-climate sampling utilities.

Runtime routing should use real SOLWEIG/SOLWEIG-GPU UTCI rasters. The
deterministic helper remains available for isolated tests and explicit
development fallback only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
from statistics import fmean
from typing import Iterable, Sequence

Coordinate = tuple[float, float]
EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class MicroclimateStats:
    """Summary of UTCI samples collected along a geometry."""

    mean_utci: float
    min_utci: float
    max_utci: float
    heat_dose: float
    shade_fraction: float
    sample_count: int


@dataclass(frozen=True)
class SolarPosition:
    """Solar altitude and azimuth in degrees for a route sample point."""

    altitude_deg: float
    azimuth_deg: float


def hour_from_time(value: datetime | float | int | None) -> float:
    """Return fractional local hour from a datetime or numeric hour."""

    if value is None:
        return 12.0
    if isinstance(value, datetime):
        return value.hour + value.minute / 60 + value.second / 3600
    return float(value) % 24


def _coerce_datetime(value: datetime | float | int | None) -> datetime:
    if isinstance(value, datetime):
        return value
    now = datetime.now()
    if value is None:
        return now
    hour = float(value) % 24
    whole_hour = int(hour)
    minute = int((hour - whole_hour) * 60)
    second = int(round((((hour - whole_hour) * 60) - minute) * 60))
    if second == 60:
        minute += 1
        second = 0
    if minute == 60:
        whole_hour = (whole_hour + 1) % 24
        minute = 0
    return now.replace(hour=whole_hour, minute=minute, second=second, microsecond=0)


def solar_position(coordinate: Coordinate, departure_time: datetime | float | int | None) -> SolarPosition:
    """Approximate solar altitude and azimuth for shade-orientation fallback.

    The implementation follows the NOAA fractional-year approximation. Aware
    datetimes use their UTC offset; naive datetimes are treated as server-local
    civil time, falling back to the nearest longitude time zone if needed.
    """

    latitude, longitude = coordinate
    dt = _coerce_datetime(departure_time)
    if dt.tzinfo is not None and dt.utcoffset() is not None:
        timezone_offset_hours = dt.utcoffset().total_seconds() / 3600.0
    else:
        local_offset = dt.astimezone().utcoffset()
        timezone_offset_hours = (
            local_offset.total_seconds() / 3600.0
            if local_offset is not None
            else round(longitude / 15.0)
        )

    fractional_hour = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
    day_of_year = dt.timetuple().tm_yday
    gamma = 2.0 * math.pi / 365.0 * (day_of_year - 1 + (fractional_hour - 12.0) / 24.0)
    equation_of_time_min = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2.0 * gamma)
        - 0.040849 * math.sin(2.0 * gamma)
    )
    declination_rad = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2.0 * gamma)
        + 0.000907 * math.sin(2.0 * gamma)
        - 0.002697 * math.cos(3.0 * gamma)
        + 0.00148 * math.sin(3.0 * gamma)
    )

    time_offset_min = equation_of_time_min + 4.0 * longitude - 60.0 * timezone_offset_hours
    true_solar_time_min = (fractional_hour * 60.0 + time_offset_min) % 1440.0
    hour_angle_deg = true_solar_time_min / 4.0 - 180.0
    if hour_angle_deg < -180.0:
        hour_angle_deg += 360.0

    latitude_rad = math.radians(latitude)
    hour_angle_rad = math.radians(hour_angle_deg)
    cos_zenith = (
        math.sin(latitude_rad) * math.sin(declination_rad)
        + math.cos(latitude_rad) * math.cos(declination_rad) * math.cos(hour_angle_rad)
    )
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    zenith_rad = math.acos(cos_zenith)
    altitude_deg = 90.0 - math.degrees(zenith_rad)

    sin_zenith = math.sin(zenith_rad)
    if abs(sin_zenith) < 1e-9:
        azimuth_deg = 180.0
    else:
        azimuth_cos = (
            math.sin(latitude_rad) * math.cos(zenith_rad) - math.sin(declination_rad)
        ) / (math.cos(latitude_rad) * sin_zenith)
        azimuth_cos = max(-1.0, min(1.0, azimuth_cos))
        azimuth = math.degrees(math.acos(azimuth_cos))
        azimuth_deg = (azimuth + 180.0) % 360.0 if hour_angle_deg > 0.0 else (540.0 - azimuth) % 360.0

    return SolarPosition(altitude_deg=altitude_deg, azimuth_deg=azimuth_deg)


def get_utci_raster(x: float, y: float, hour: datetime | float | int | None) -> float:
    """Return a deterministic synthetic UTCI value for a coordinate and time.

    Args:
        x: Longitude in decimal degrees.
        y: Latitude in decimal degrees.
        hour: Datetime or hour of day in local time.

    TODO: Replace this placeholder with a raster lookup backed by SOLWEIG-GPU
    UTCI or mean radiant temperature products at the requested timestamp.
    """

    h = hour_from_time(hour)
    daily_cycle = math.cos((h - 14.0) / 24.0 * 2.0 * math.pi)
    urban_heat = 1.8 * math.sin((x + 77.0) * 48.0) * math.cos((y - 38.0) * 35.0)
    shade_cooling = -2.4 * max(0.0, math.sin((x * 91.0) + (y * 73.0)))
    moisture_relief = -0.8 * math.cos((x - y) * 19.0)
    return 27.0 + 6.2 * daily_cycle + urban_heat + shade_cooling + moisture_relief


def cool_utci_threshold(hour: datetime | float | int | None) -> float:
    """Approximate the lower-city-field UTCI threshold used as shade proxy."""

    h = hour_from_time(hour)
    return 25.5 + 3.2 * math.cos((h - 14.0) / 24.0 * 2.0 * math.pi)


def haversine_distance_m(a: Coordinate, b: Coordinate) -> float:
    """Compute great-circle distance between two ``(lat, lon)`` points."""

    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    h = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def offset_coordinate(origin: Coordinate, north_m: float, east_m: float) -> Coordinate:
    """Move a coordinate by local north/east metre offsets."""

    lat, lon = origin
    lat_delta = north_m / 111_320.0
    lon_scale = max(0.1, math.cos(math.radians(lat)))
    lon_delta = east_m / (111_320.0 * lon_scale)
    return lat + lat_delta, lon + lon_delta


def densify_geometry(points: Sequence[Coordinate], spacing_m: float = 5.0) -> list[Coordinate]:
    """Interpolate a polyline so no segment is much longer than ``spacing_m``.

    The returned geometry always includes the first and last input points.
    """

    if spacing_m <= 0:
        raise ValueError("spacing_m must be positive")
    if not points:
        return []
    if len(points) == 1:
        return [points[0]]

    dense: list[Coordinate] = [points[0]]
    for start, end in zip(points, points[1:]):
        segment_m = haversine_distance_m(start, end)
        steps = max(1, int(math.ceil(segment_m / spacing_m)))
        for idx in range(1, steps + 1):
            fraction = idx / steps
            lat = start[0] + (end[0] - start[0]) * fraction
            lon = start[1] + (end[1] - start[1]) * fraction
            candidate = (lat, lon)
            if candidate != dense[-1]:
                dense.append(candidate)
    return dense


def sample_utci_values(
    points: Iterable[Coordinate],
    departure_time: datetime | float | int | None,
    raster_path: str | Path | None = None,
) -> list[float]:
    """Sample UTCI values at each ``(lat, lon)`` coordinate.

    When ``raster_path`` is provided, values are read from a real GeoTIFF and
    missing coverage raises an error. Otherwise the deterministic development
    fallback is used.
    """

    if raster_path is not None:
        from routing_backend.raster_data import sample_raster_values

        values = sample_raster_values(Path(raster_path), points)
        if values:
            return values
        raise ValueError(f"No valid UTCI samples found in raster {raster_path}")

    return [get_utci_raster(lon, lat, departure_time) for lat, lon in points]


def summarize_utci_samples(
    values: Sequence[float],
    departure_time: datetime | float | int | None,
    comfort_threshold: float = 26.0,
) -> MicroclimateStats:
    """Convert raw UTCI samples into route or edge-level statistics."""

    if not values:
        raise ValueError("At least one UTCI sample is required")

    cool_threshold = cool_utci_threshold(departure_time)
    heat_excess = [max(0.0, value - comfort_threshold) for value in values]
    shade_count = sum(1 for value in values if value <= cool_threshold)
    return MicroclimateStats(
        mean_utci=fmean(values),
        min_utci=min(values),
        max_utci=max(values),
        heat_dose=fmean(heat_excess),
        shade_fraction=shade_count / len(values),
        sample_count=len(values),
    )


def sample_microclimate_along_geometry(
    points: Sequence[Coordinate],
    departure_time: datetime | float | int | None,
    spacing_m: float = 5.0,
    comfort_threshold: float = 26.0,
    raster_path: str | Path | None = None,
) -> MicroclimateStats:
    """Densify a geometry and return UTCI/shade statistics along it."""

    dense_points = densify_geometry(points, spacing_m=spacing_m)
    values = sample_utci_values(dense_points, departure_time, raster_path=raster_path)
    return summarize_utci_samples(
        values,
        departure_time=departure_time,
        comfort_threshold=comfort_threshold,
    )
