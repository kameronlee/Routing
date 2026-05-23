import json
from datetime import datetime

import numpy as np
import rasterio
from rasterio.transform import from_origin

from routing_backend.real_features import RealFeatureContext, RealFeaturePaths, discover_real_feature_paths


def _write_raster(path, values) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-77.10, 38.90, 0.01, 0.01),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(values.astype("float32"), 1)


def _write_traffic(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"AADT": 1000},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-77.096, 38.896], [-77.084, 38.884]],
                },
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_real_feature_context_uses_lidar_canopy_height_without_landcover(tmp_path) -> None:
    canopy_path = tmp_path / "canopy_height_1m.tif"
    traffic_path = tmp_path / "traffic.geojson"
    _write_raster(canopy_path, np.array([[8.0, 4.0], [3.0, 0.0]], dtype=np.float32))
    _write_traffic(traffic_path)

    context = RealFeatureContext(
        RealFeaturePaths(
            utci_raster=tmp_path / "unused_utci.tif",
            canopy_height_rasters=(canopy_path,),
            canopy_class_rasters=(),
            landcover_rasters=(),
            traffic_geojson=traffic_path,
        )
    )
    try:
        attrs = context.edge_attributes([(38.895, -77.095), (38.885, -77.085)], {}, 100.0)
    finally:
        context.close()

    assert attrs["tree_canopy_fraction"] > 0
    assert attrs["canopy_height_mean_m"] > 0
    assert attrs["landcover_green_fraction"] == 0
    assert attrs["scenic_score"] > 0
    assert 0 <= attrs["noise_score"] <= 1


def test_discover_real_feature_paths_accepts_lidar_canopy_without_landcover(tmp_path) -> None:
    output_dir = tmp_path / "processed" / "solweig_outputs"
    output_dir.mkdir(parents=True)
    (output_dir / "utci_2026-07-01_14.tif").touch()
    _write_raster(tmp_path / "processed" / "rasters" / "canopy_height_1m.tif", np.ones((2, 2)))
    _write_traffic(tmp_path / "raw" / "traffic_noise" / "ddot_traffic_volume_2023.geojson")

    paths = discover_real_feature_paths(tmp_path, datetime(2026, 7, 1, 14))

    assert paths.canopy_height_rasters
    assert paths.landcover_rasters == ()
