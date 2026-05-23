from fastapi.testclient import TestClient
import numpy as np
import rasterio
from rasterio.transform import from_origin

from routing_backend.api import Settings, create_app


def test_health_endpoint() -> None:
    client = TestClient(create_app(Settings(prefer_local_data=False)))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_route_endpoint_returns_candidate() -> None:
    client = TestClient(
        create_app(
            Settings(
                prefer_local_data=False,
                allow_synthetic_graph=True,
                allow_synthetic_microclimate=True,
            )
        )
    )

    response = client.post(
        "/route",
        json={
            "origin": {"lat": 38.8805, "lon": -77.0920},
            "destination": {"lat": 38.8828, "lon": -77.0896},
            "departure_time": "2026-07-01T14:00:00",
            "descriptors": ["heat sensitive", "quiet"],
            "detour_ratio": 0.4,
            "max_candidates": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["graph_source"] == "synthetic"
    assert len(payload["candidates"]) >= 1
    candidate = payload["candidates"][0]
    assert candidate["distance_m"] > 0
    assert 0 <= candidate["shade_fraction"] <= 1


def test_utci_endpoint_returns_real_tile(tmp_path) -> None:
    output_dir = tmp_path / "processed" / "solweig_outputs"
    output_dir.mkdir(parents=True)
    raster_path = output_dir / "utci_2026-07-01_14.tif"
    values = np.full((5, 5), 28.0, dtype=np.float32)
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=5,
        width=5,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-77.093, 38.884, 0.001, 0.001),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(values, 1)

    client = TestClient(create_app(Settings(data_dir=tmp_path, prefer_local_data=False)))

    response = client.get("/utci?lat=38.8816&lon=-77.0910&cells=3&time=2026-07-01T14:00:00")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["values"]) == 9
    assert payload["min_utci"] <= payload["mean_utci"] <= payload["max_utci"]


def test_data_status_endpoint_reports_missing_bundle(tmp_path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path)))

    response = client.get("/data/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["manifest_exists"] is False
    assert payload["graph_exists"] is False
    assert payload["dem_exists"] is False
    assert payload["strict_real_ready"] is False
    assert "SOLWEIG UTCI raster" in payload["missing_required_layers"]


def test_route_can_require_real_utci(tmp_path) -> None:
    client = TestClient(
        create_app(
            Settings(
                data_dir=tmp_path,
                prefer_local_data=False,
                allow_synthetic_graph=True,
            )
        )
    )

    response = client.post(
        "/route",
        json={
            "origin": {"lat": 38.8805, "lon": -77.0920},
            "destination": {"lat": 38.8828, "lon": -77.0896},
            "departure_time": "2026-07-01T14:00:00",
        },
    )

    assert response.status_code == 503
