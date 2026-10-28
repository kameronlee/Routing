from dataclasses import replace

import networkx as nx

from routing_backend.experiment_config import ExperimentConfig, load_experiment_config
from routing_backend.experiment_io import read_csv, write_csv
from routing_backend import review_sensitivity as review
from routing_backend.route_engine import EdgeFeatures


def test_review_sensitivity_records_actual_weight_settings_and_fixed_reporting(tmp_path, monkeypatch):
    config = load_experiment_config("configs/dc_snapshot_review3466.yaml")
    config = replace(config, output_dir=tmp_path / "results", detour_ratios=(0.05,))
    graph = nx.MultiDiGraph()
    graph.add_node("a", x=0, y=0)
    graph.add_node("b", x=.001, y=0)
    graph.add_edge("a", "b", length=100, features=EdgeFeatures(
        100, 100, 26, 30, 2, .5, .5, 0, 0, 0, utci_samples=(22,30)))
    pair_file = tmp_path / "pairs.csv"
    write_csv(pair_file, [dict(pair_id="1", origin_node="a", destination_node="b",
                               baseline_shortest_distance_m=100)])
    class Context:
        def close(self):
            pass
    monkeypatch.setattr(ExperimentConfig, "require_existing_inputs", lambda _self: None)
    monkeypatch.setattr(review, "load_experiment_graph", lambda _config: graph)
    monkeypatch.setattr(review, "build_real_feature_context", lambda _config: Context())
    monkeypatch.setattr(review, "_build_feature_graph_for_pair", lambda *args, **kwargs: graph.copy())
    output = review.run_review_sensitivity(config, od_pairs_path=pair_file, subset_size=1)
    rows = read_csv(output)
    assert len(rows) == 35
    assert all(row["success"] == "true" for row in rows)
    # Thresholds/offsets change selection features, but all paths are scored
    # against the same original 22/30 C samples at tau=26 (H=2 K).
    assert all(float(row["heat_dose"]) == 2 for row in rows)
    thermal_off = next(row for row in rows if row["method"] == "weight_cool_x0")
    assert '"weight_cool": 0.0' in thermal_off["perturbation"]
