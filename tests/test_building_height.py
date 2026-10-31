"""Guard against treating terrain elevation as above-ground building height."""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from scripts.derive_building_height import derive_height


def write_raster(path, data, *, shift=0):
    with rasterio.open(path, "w", driver="GTiff", height=2, width=2, count=1,
                       dtype="float32", crs="EPSG:26985", nodata=-9999,
                       transform=from_origin(400000 + shift, 130000, 1, 1)) as raster:
        raster.write(np.array(data, dtype="float32"), 1)


def test_height_subtracts_terrain_preserves_nodata_and_clamps_negative(tmp_path):
    write_raster(tmp_path / "dsm.tif", [[110, 99], [-9999, 250]])
    write_raster(tmp_path / "dem.tif", [[100, 100], [10, 200]])
    derive_height(tmp_path / "dsm.tif", tmp_path / "dem.tif", tmp_path / "height.tif")
    with rasterio.open(tmp_path / "height.tif") as raster:
        np.testing.assert_array_equal(raster.read(1), [[10, 0], [-9999, 50]])
        assert raster.tags()["units"] == "m"


def test_height_rejects_different_grids(tmp_path):
    write_raster(tmp_path / "dsm.tif", [[110, 99], [10, 250]], shift=1)
    write_raster(tmp_path / "dem.tif", [[100, 100], [10, 200]])
    with pytest.raises(ValueError, match="identical grids"):
        derive_height(tmp_path / "dsm.tif", tmp_path / "dem.tif", tmp_path / "height.tif")
