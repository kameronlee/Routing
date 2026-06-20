import numpy as np
import rasterio
from rasterio.transform import from_origin

from scripts.fill_utci_nans import fill_utci_nans


def test_fill_utci_nans_repairs_missing_cells(tmp_path) -> None:
    source = tmp_path / "utci.tif"
    destination = tmp_path / "utci_filled.tif"
    values = np.array(
        [
            [30.0, 30.0, 30.0],
            [30.0, np.nan, 32.0],
            [32.0, 32.0, 32.0],
        ],
        dtype=np.float32,
    )
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        height=3,
        width=3,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-77.0, 39.0, 0.001, 0.001),
    ) as dataset:
        dataset.write(values, 1)

    summary = fill_utci_nans(source, destination, max_search_distance=3, smoothing_iterations=0)

    with rasterio.open(destination) as dataset:
        repaired = dataset.read(1, masked=False)

    assert summary["missing_before"] == 1
    assert summary["missing_after"] == 0
    assert np.isfinite(repaired).all()
