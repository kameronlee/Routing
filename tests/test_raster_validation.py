import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from routing_backend.raster_validation import (
    compare_shaded_vs_sunlit_utci,
    compute_overlap_bounds,
    compute_raster_stats,
    save_shaded_sunlit_boxplot_png,
    validate_raster_pair,
)


def _write_raster(path, values, nodata=-9999.0) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-77.0, 39.0, 0.01, 0.01),
        nodata=nodata,
    ) as dataset:
        dataset.write(values.astype("float32"), 1)


def test_raster_stats_handle_nodata(tmp_path) -> None:
    path = tmp_path / "utci.tif"
    _write_raster(path, np.array([[20.0, -9999.0], [30.0, 40.0]], dtype=np.float32))

    stats = compute_raster_stats(path)

    assert stats["valid_count"] == 3
    assert stats["min"] == 20
    assert stats["max"] == 40
    assert stats["nodata_count"] == 1


def test_shaded_vs_sunlit_comparison() -> None:
    report = compare_shaded_vs_sunlit_utci([20, 33, 22, 35], [0, 1, 0, 1])

    assert report["shaded_count"] == 2
    assert report["sunlit_count"] == 2
    assert report["median_utci_shaded"] == 21
    assert report["median_utci_sunlit"] == 34
    assert report["warnings"] == []


def test_validate_raster_pair_reports_overlap_and_shadow_convention(tmp_path) -> None:
    utci = tmp_path / "utci.tif"
    shadow = tmp_path / "shadow.tif"
    _write_raster(utci, np.array([[20.0, 33.0], [22.0, 35.0]], dtype=np.float32))
    _write_raster(shadow, np.array([[0.0, 1.0], [0.0, 1.0]], dtype=np.float32))

    overlap = compute_overlap_bounds(utci, shadow)
    report = validate_raster_pair(utci, shadow, sample_count=200, seed=1)

    assert overlap["overlap"] is True
    assert report["shadow_value_report"]["likely_convention"] == "direct_solweig_shadow_0_shade_1_sun"
    assert report["paired_sample_count"] > 0


def test_shaded_sunlit_boxplot_png_handles_installed_matplotlib(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mplconfig"))
    pytest.importorskip("matplotlib.pyplot")
    output = tmp_path / "boxplot.png"

    save_shaded_sunlit_boxplot_png([20.0, 33.0, 21.0, 34.0], [0.0, 1.0, 0.0, 1.0], output)

    assert output.exists()
    assert output.stat().st_size > 0
