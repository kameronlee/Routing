from routing_backend.result_metrics import (
    excess_distance_ratio,
    heat_dose_reduction,
    heat_dose_reduction_percent,
    max_utci_reduction,
    mean_utci_reduction,
    percent_change,
    route_overlap_jaccard,
    shade_fraction_increase,
    summarize_by_group,
)


def test_metric_definitions() -> None:
    assert excess_distance_ratio(120, 100) == 0.2
    assert heat_dose_reduction(5, 3) == 2
    assert heat_dose_reduction_percent(5, 3) == 40
    assert mean_utci_reduction(31, 29) == 2
    assert max_utci_reduction(35, 30) == 5
    assert shade_fraction_increase(0.2, 0.5) == 0.3
    assert percent_change(100, 120) == 20


def test_metric_zero_denominators_return_none() -> None:
    assert percent_change(0, 1) is None
    assert heat_dose_reduction_percent(0, 0) is None
    assert excess_distance_ratio(10, 0) is None


def test_route_overlap_jaccard() -> None:
    assert route_overlap_jaccard(["a", "b"], ["b", "c"]) == 1 / 3
    assert route_overlap_jaccard([], []) == 1.0


def test_summarize_by_group() -> None:
    rows = [
        {"method": "a", "value": "1", "success": "true"},
        {"method": "a", "value": "3", "success": "false"},
        {"method": "b", "value": "5", "success": "true"},
    ]

    summaries = summarize_by_group(rows, ["method"], ["value"])
    by_method = {row["method"]: row for row in summaries}

    assert by_method["a"]["count"] == 2
    assert by_method["a"]["value_mean"] == 2
    assert by_method["a"]["success_rate"] == 0.5
    assert by_method["b"]["value_median"] == 5
