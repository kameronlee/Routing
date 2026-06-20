from datetime import date

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from scripts.run_solweig_gpu import (
    _assign_shifted_bush,
    _published_geotiff_profile,
    filter_metfile_to_hour,
    parse_metfile_hours,
    publish_solweig_outputs,
)


def test_filter_metfile_to_hour(tmp_path) -> None:
    source = tmp_path / "met.txt"
    source.write_text(
        "\n".join(
            [
                "iy id it imin Q* QH QE Qs Qf Wind RH Td press rain Kdn snow ldown fcld wuh xsmd lai_hr Kdiff Kdir Wd",
                "2026 182 8 0 -999 -999 -999 -999 -999 1 50 25 101 0 400 -999 -999 -999 -999 -999 -999 -999 -999 180",
                "2026 182 14 0 -999 -999 -999 -999 -999 2 60 32 101 0 800 -999 -999 -999 -999 -999 -999 -999 -999 210",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    destination = tmp_path / "hour.txt"

    filter_metfile_to_hour(source, destination, 14)

    assert parse_metfile_hours(destination) == [14]


def test_parse_metfile_hours(tmp_path) -> None:
    source = tmp_path / "met.txt"
    source.write_text(
        "iy id it imin Q* QH QE Qs Qf Wind RH Td press rain Kdn snow ldown fcld wuh xsmd lai_hr Kdiff Kdir Wd\n"
        "2026 182 16 0 -999 -999 -999 -999 -999 2 60 32 101 0 800 -999 -999 -999 -999 -999 -999 -999 -999 210\n",
        encoding="utf-8",
    )

    assert parse_metfile_hours(source) == [16]


def test_published_geotiff_profile_overrides_invalid_source_blocks() -> None:
    source_profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "count": 1,
        "blockxsize": 1020,
        "blockysize": 2,
        "tiled": False,
    }

    profile = _published_geotiff_profile(source_profile, height=1234, width=5678, transform=None)

    assert profile["tiled"] is True
    assert profile["blockxsize"] == 512
    assert profile["blockysize"] == 512
    assert profile["blockxsize"] % 16 == 0
    assert profile["blockysize"] % 16 == 0


def test_publish_solweig_outputs_includes_optional_shadow_raster(tmp_path) -> None:
    work_dir = tmp_path / "work"
    tile_dir = work_dir / "output_folder" / "0_0"
    tile_dir.mkdir(parents=True)
    met_file = tmp_path / "met.txt"
    met_file.write_text(
        "iy id it imin Q* QH QE Qs Qf Wind RH Td press rain Kdn snow ldown fcld wuh xsmd lai_hr Kdiff Kdir Wd\n"
        "2026 147 14 0 -999 -999 -999 -999 -999 2 60 32 101 0 800 -999 -999 -999 -999 -999 -999 -999 -999 210\n",
        encoding="utf-8",
    )
    profile = {
        "driver": "GTiff",
        "height": 2,
        "width": 2,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_origin(0.0, 2.0, 1.0, 1.0),
    }
    for name, value in [("UTCI_0_0.tif", 30.0), ("Shadow_0_0.tif", 1.0)]:
        with rasterio.open(tile_dir / name, "w", **profile) as dataset:
            dataset.write(np.full((2, 2), value, dtype="float32"), 1)

    written = publish_solweig_outputs(work_dir, tmp_path / "published", date(2026, 5, 27), met_file)

    assert tmp_path / "published" / "utci_2026-05-27_14.tif" in written
    assert tmp_path / "published" / "shadow_2026-05-27_14.tif" in written


def test_assign_shifted_bush_skips_empty_source_edge_slice() -> None:
    torch = pytest.importorskip("torch")

    tempbush = torch.zeros((1020, 2))
    bush = torch.ones((1020, 2))

    _assign_shifted_bush(
        tempbush,
        bush,
        xp1=1,
        xp2=1020,
        yp1=1,
        yp2=2,
        xc1=0,
        xc2=0,
        yc1=1,
        yc2=2,
        dz=torch.tensor(1.0),
    )

    assert torch.count_nonzero(tempbush).item() == 0


def test_assign_shifted_bush_clips_to_matching_window() -> None:
    torch = pytest.importorskip("torch")

    tempbush = torch.zeros((4, 4))
    bush = torch.arange(16, dtype=torch.float32).reshape(4, 4)

    _assign_shifted_bush(
        tempbush,
        bush,
        xp1=1,
        xp2=4,
        yp1=1,
        yp2=4,
        xc1=1,
        xc2=4,
        yc1=1,
        yc2=4,
        dz=torch.tensor(1.0),
    )

    assert torch.equal(tempbush, bush - 1.0)
