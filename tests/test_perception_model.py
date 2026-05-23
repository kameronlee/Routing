from routing_backend.perception_model import compute_noise_score, compute_scenic_score, compute_slope


def test_perception_scores_are_bounded() -> None:
    edge = {"highway": "path", "landuse": "park", "tree_canopy_fraction": 0.8}

    assert 0 <= compute_scenic_score(edge) <= 1
    assert 0 <= compute_noise_score(edge) <= 1


def test_busy_roads_are_noisier_than_paths() -> None:
    assert compute_noise_score({"highway": "primary", "lanes": 4}) > compute_noise_score({"highway": "path"})


def test_compute_slope_from_elevations() -> None:
    slope, elevation_change = compute_slope({}, length_m=100, elevation_start_m=10, elevation_end_m=15)

    assert slope == 0.05
    assert elevation_change == 5
