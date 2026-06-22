from datetime import datetime

import numpy as np
import rasterio
from rasterio.transform import from_origin

from routing_backend.raster_data import find_time_raster, raster_timestamp, sample_raster_values


def test_find_time_raster_prefers_matching_hour(tmp_path) -> None:
    output_dir = tmp_path / "processed" / "solweig_outputs"
    output_dir.mkdir(parents=True)
    morning = output_dir / "utci_2026-07-01_08.tif"
    afternoon = output_dir / "utci_2026-07-01_14.tif"
    morning.write_bytes(b"fake")
    afternoon.write_bytes(b"fake")

    result = find_time_raster(tmp_path, "utci", datetime(2026, 7, 1, 13, 30))

    assert result == afternoon


def test_find_time_raster_prefers_newest_date_when_requested_date_is_missing(tmp_path) -> None:
    output_dir = tmp_path / "processed" / "solweig_outputs"
    output_dir.mkdir(parents=True)
    older = output_dir / "utci_2026-05-27_14.tif"
    newest = output_dir / "utci_2026-06-19_14.tif"
    older.write_bytes(b"fake")
    newest.write_bytes(b"fake")

    result = find_time_raster(tmp_path, "utci", datetime(2026, 6, 20, 14, 0))

    assert result == newest
    assert raster_timestamp(result) == datetime(2026, 6, 19, 14, 0)


def test_sample_raster_values_rejects_coordinates_outside_raster_bounds(tmp_path) -> None:
    raster_path = tmp_path / "utci_2026-06-19_14.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-77.1, 38.9, 0.01, 0.01),
    ) as dataset:
        dataset.write(np.full((2, 2), 30.0, dtype=np.float32), 1)

    assert sample_raster_values(raster_path, [(38.895, -77.095)]) == [30.0]
    assert sample_raster_values(raster_path, [(0.0, 0.0)]) == []
