"""Regression tests for scientific and budget failures raised in review 3466."""

from dataclasses import replace

import networkx as nx
import pytest

from routing_backend.baseline_methods import project_graph_for_method, route_with_method
from routing_backend.paired_comparison import common_accepted_rows, paired_heat_contrasts
from routing_backend.preferences import Preference
from routing_backend.route_engine import EdgeFeatures, NoPathWithinBudget, resource_constrained_routes


def _edge(length, utci):
    return EdgeFeatures(length, length, utci, utci, max(0, utci-26), 0, 0.5, 0, 0, 0)


def _graph():
    graph = nx.MultiDiGraph()
    graph.add_node("a", x=0, y=0)
    graph.add_node("b", x=0.001, y=0)
    graph.add_edge("a", "b", key="short", length=100, features=_edge(100, 36))
    graph.add_edge("a", "b", key="cool", length=150, features=_edge(150, 24))
    return graph


def test_capped_fallback_chooses_shortest_parallel_edge_and_records_source():
    route = resource_constrained_routes(_graph(), "a", "b", Preference(),
                                        delta=0.05, max_candidates=1, max_expansions=0)[0]
    assert route.distance_m == 100
    assert route.edge_ids == ["a->b:short"]
    assert route.route_source == "shortest_fallback"
    assert route.search_truncated and route.search_stop_reason == "expansion_limit"


def test_original_graph_budget_is_not_rebased_after_coverage_removal():
    graph = _graph()
    graph.remove_edge("a", "b", "short")
    with pytest.raises(NoPathWithinBudget):
        resource_constrained_routes(graph, "a", "b", Preference(),
                                    delta=0.30, maximum_distance_m=130)


def test_method_adapter_propagates_budget_and_route_provenance():
    route, _ = route_with_method(_graph(), "a", "b", "proposed_full", detour_ratio=0.9,
                                comfort_threshold=26, maximum_distance_m=105, max_expansions=0)
    assert route.distance_m <= 105
    assert route.maximum_distance_m == 105
    assert route.route_source == "shortest_fallback"
    assert route.search_truncated


def test_identity_projection_preserves_sampled_exceedance():
    graph = _graph()
    # Two samples, 22 C and 30 C: H=2 K, even though mean U=26 C.
    graph.edges["a", "b", "short"]["features"] = replace(
        _edge(100, 26), max_utci=30, heat_dose=2, utci_samples=(22, 30))
    projected = project_graph_for_method(graph, "proposed_full", comfort_threshold=26)
    assert projected.edges["a", "b", "short"]["features"].heat_dose == 2


def test_offset_and_threshold_are_applied_to_samples_before_averaging():
    graph = _graph()
    for _, _, data in graph.edges(data=True):
        data["features"] = replace(data["features"], mean_utci=26, max_utci=30,
                                   heat_dose=2, utci_samples=(22, 30))
    projected = project_graph_for_method(graph, "proposed_full", comfort_threshold=28, utci_offset_c=1)
    assert projected.edges["a", "b", "short"]["features"].heat_dose == 1.5


def _records():
    return [dict(pair_id=pair, method=method, detour_ratio=budget, heat_dose=heat,
                 success=success, study_name="test", config_hash="cfg", run_id="run", raster_timestamp="hour")
            for pair, method, budget, heat, success in [
                ("1", "shortest_distance", "0.10", 5, "true"),
                ("1", "a", "0.1", 3, "true"), ("1", "b", "0.1", 4, "true"),
                ("2", "shortest_distance", "0.1", 8, "true"),
                ("2", "a", "0.1", 1, "true"), ("2", "b", "0.1", "", "false"),
            ]]


def test_common_subset_excludes_failed_and_missing_methods():
    rows = common_accepted_rows(_records(), ["a", "b"])
    assert len(rows) == 3
    assert {row["pair_id"] for row in rows} == {"1"}
    assert common_accepted_rows(_records(), ["a", "b", "missing"]) == []


def test_common_subset_never_pairs_different_runs_and_rejects_duplicates():
    rows = _records()
    rows[2]["run_id"] = "another-run"
    assert common_accepted_rows(rows, ["a", "b"]) == []
    with pytest.raises(ValueError, match="Duplicate"):
        common_accepted_rows([*_records(), _records()[0]], ["a", "b"])


def test_paired_contrast_uses_same_records_and_does_not_invent_single_cluster_ci():
    rows = paired_heat_contrasts(_records(), ["a", "b"])
    assert len(rows) == 2  # per budget and pooled, same sole common pair
    assert all(row["mean_H_b_minus_H_a_K"] == 1 for row in rows)
    assert all(row["common_records"] == 1 and row["ci95_low_K"] is None for row in rows)

