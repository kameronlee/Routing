import threading

from fastapi.testclient import TestClient
import numpy as np
import rasterio
from rasterio.transform import from_origin

import routing_backend.api as api_module
from routing_backend.api import CoordinateModel, Settings, _looks_like_dc_request, build_data_status, create_app


def test_health_endpoint() -> None:
    client = TestClient(create_app(Settings(prefer_local_data=False)))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_explicit_dc_city_uses_local_graph_even_for_out_of_coverage_coordinates() -> None:
    outside = CoordinateModel(lat=38.7, lon=-77.3)
    capitol = CoordinateModel(lat=38.889939, lon=-77.009050)

    assert _looks_like_dc_request(outside, capitol, "Washington, District of Columbia, USA")
    assert not _looks_like_dc_request(outside, capitol, "Baltimore, Maryland, USA")


def test_health_does_not_wait_for_background_preload(monkeypatch) -> None:
    preload_started = threading.Event()
    release_preload = threading.Event()

    def slow_preload(_app, _settings) -> None:
        preload_started.set()
        release_preload.wait(timeout=2)

    monkeypatch.setattr(api_module, "_preload_local_graph", slow_preload)
    try:
        with TestClient(create_app(Settings(preload_local_graph=True))) as client:
            assert preload_started.wait(timeout=1)
            response = client.get("/health")
            assert response.status_code == 200
    finally:
        release_preload.set()


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
    assert payload["origin_snap_distance_m"] >= 0
    assert payload["destination_snap_distance_m"] >= 0
    assert isinstance(payload["warnings"], list)
    candidate = payload["candidates"][0]
    assert candidate["distance_m"] > 0
    assert 0 <= candidate["shade_fraction"] <= 1


def test_route_rejects_locations_beyond_snap_limit() -> None:
    client = TestClient(
        create_app(
            Settings(
                prefer_local_data=False,
                allow_synthetic_graph=True,
                allow_synthetic_microclimate=True,
                max_snap_distance_m=1.0,
            )
        )
    )

    response = client.post(
        "/route",
        json={
            "origin": {"lat": 38.8805, "lon": -77.0920},
            "destination": {"lat": 38.8828, "lon": -77.0896},
        },
    )

    assert response.status_code == 422
    assert "outside the supported street-network coverage" in response.json()["detail"]


def test_route_accepts_bounded_landmark_snap_tolerance() -> None:
    client = TestClient(
        create_app(
            Settings(
                prefer_local_data=False,
                allow_synthetic_graph=True,
                allow_synthetic_microclimate=True,
                max_snap_distance_m=1.0,
            )
        )
    )

    response = client.post(
        "/route",
        json={
            "origin": {"lat": 38.8805, "lon": -77.0920},
            "destination": {"lat": 38.8828, "lon": -77.0896},
            "snap_tolerance_m": 400,
        },
    )

    assert response.status_code == 200


def test_route_rejects_excessive_landmark_snap_tolerance() -> None:
    client = TestClient(create_app(Settings(prefer_local_data=False)))

    response = client.post(
        "/route",
        json={
            "origin": {"lat": 38.8805, "lon": -77.0920},
            "destination": {"lat": 38.8828, "lon": -77.0896},
            "snap_tolerance_m": 401,
        },
    )

    assert response.status_code == 422


def test_single_priority_scenic_route_never_ranks_below_baseline() -> None:
    client = TestClient(
        create_app(
            Settings(
                prefer_local_data=False,
                allow_synthetic_graph=True,
                allow_synthetic_microclimate=True,
            )
        )
    )
    common = {
        "origin": {"lat": 38.8805, "lon": -77.0920},
        "destination": {"lat": 38.8828, "lon": -77.0896},
        "detour_ratio": 0.4,
        "max_candidates": 3,
    }

    shortest = client.post("/route", json={**common, "objective": "shortest"})
    scenic = client.post("/route", json={**common, "objective": "comfort", "descriptors": ["scenic"]})

    assert shortest.status_code == 200
    assert scenic.status_code == 200
    assert scenic.json()["candidates"][0]["scenic_score"] >= shortest.json()["candidates"][0]["scenic_score"]


def test_candidate_response_limit_does_not_change_primary_route() -> None:
    client = TestClient(
        create_app(
            Settings(
                prefer_local_data=False,
                allow_synthetic_graph=True,
                allow_synthetic_microclimate=True,
                route_candidate_path_limit=10,
            )
        )
    )
    common = {
        "origin": {"lat": 38.8805, "lon": -77.0920},
        "destination": {"lat": 38.8828, "lon": -77.0896},
        "detour_ratio": 0.4,
    }

    one = client.post("/route", json={**common, "max_candidates": 1})
    many = client.post("/route", json={**common, "max_candidates": 5})

    assert one.status_code == 200
    assert many.status_code == 200
    assert one.json()["candidates"][0]["edge_ids"] == many.json()["candidates"][0]["edge_ids"]


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
    assert payload["time"] == "2026-07-01T14:00:00"
    assert payload["requested_time"] == "2026-07-01T14:00:00"
    assert payload["utci_source"].endswith("utci_2026-07-01_14.tif")

    fallback = client.get("/utci?lat=38.8816&lon=-77.0910&cells=1&time=2026-07-02T14:00:00")
    assert fallback.status_code == 200
    assert fallback.json()["time"] == "2026-07-01T14:00:00"
    assert fallback.json()["requested_time"] == "2026-07-02T14:00:00"

    outside = client.get("/utci?lat=0&lon=0&cells=1")
    assert outside.status_code == 422
    assert "no valid UTCI raster samples" in outside.json()["detail"]


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


def test_build_data_status_reports_missing_bundle(tmp_path) -> None:
    status = build_data_status(Settings(data_dir=tmp_path))

    assert status.manifest_exists is False
    assert status.graph_exists is False
    assert status.dem_exists is False
    assert status.strict_real_ready is False
    assert "SOLWEIG UTCI raster" in status.missing_required_layers


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
