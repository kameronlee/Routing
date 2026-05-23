from datetime import datetime

from routing_backend.raster_data import find_time_raster


def test_find_time_raster_prefers_matching_hour(tmp_path) -> None:
    output_dir = tmp_path / "processed" / "solweig_outputs"
    output_dir.mkdir(parents=True)
    morning = output_dir / "utci_2026-07-01_08.tif"
    afternoon = output_dir / "utci_2026-07-01_14.tif"
    morning.write_bytes(b"fake")
    afternoon.write_bytes(b"fake")

    result = find_time_raster(tmp_path, "utci", datetime(2026, 7, 1, 13, 30))

    assert result == afternoon
