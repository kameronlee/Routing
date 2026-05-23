from datetime import datetime

from routing_backend.microclimate_model import (
    densify_geometry,
    get_utci_raster,
    sample_microclimate_along_geometry,
)


def test_get_utci_raster_is_deterministic() -> None:
    first = get_utci_raster(-77.0910, 38.8816, 14)
    second = get_utci_raster(-77.0910, 38.8816, 14)

    assert first == second


def test_densify_geometry_adds_samples() -> None:
    points = [(38.8816, -77.0910), (38.8826, -77.0910)]

    dense = densify_geometry(points, spacing_m=10)

    assert dense[0] == points[0]
    assert dense[-1] == points[-1]
    assert len(dense) > len(points)


def test_sample_microclimate_returns_summary() -> None:
    points = [(38.8816, -77.0910), (38.8826, -77.0910)]

    stats = sample_microclimate_along_geometry(
        points,
        departure_time=datetime(2026, 7, 1, 14, 0),
        spacing_m=10,
    )

    assert stats.sample_count > 2
    assert stats.min_utci <= stats.mean_utci <= stats.max_utci
    assert stats.heat_dose >= 0
    assert 0 <= stats.shade_fraction <= 1
