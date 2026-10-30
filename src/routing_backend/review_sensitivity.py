"""Prespecified weight, threshold and sampling sweeps for GeoHealth review 3466."""

from __future__ import annotations

from dataclasses import asdict
import json
from time import perf_counter

from routing_backend.baseline_methods import (
    RouteMethod, _rescore_candidate_on_graph, get_method_config,
    project_graph_for_method, route_with_method,
)
from routing_backend.benchmark_runner import (
    ROUTE_SUMMARY_COLUMNS, _build_feature_graph_for_pair, _candidate_row,
    _coerce_node_id, _failure_row, build_real_feature_context,
    load_experiment_graph, load_od_pairs,
)
from routing_backend.experiment_io import config_hash, ensure_output_layout, write_csv, write_json
from routing_backend.result_metrics import route_overlap_jaccard


def sensitivity_variants():
    variants = [("reference", {})]
    defaults = get_method_config(RouteMethod.PROPOSED_FULL, comfort_threshold=26).preference
    for field, value in asdict(defaults).items():
        if field.startswith("weight_") or field == "uncertainty_penalty":
            for multiplier in (0.0, 0.5, 2.0):
                variants.append((f"{field}_x{multiplier:g}", {
                    "preference_overrides": {field: value * multiplier},
                }))
    variants += [(f"threshold_{threshold}C", {"threshold": threshold}) for threshold in (24, 28, 32)]
    variants += [(f"sampling_{spacing}m", {"spacing": spacing}) for spacing in (5, 10, 40)]
    variants += [(f"utci_offset_{offset:+}C", {"utci_offset_c": offset}) for offset in (-2, 2)]
    variants += [(f"shade_mixing_{rate:g}", {"shade_mixing": rate}) for rate in (0.05, 0.10)]
    return variants


def run_review_sensitivity(config, *, od_pairs_path, subset_size=100, variant_settings=None):
    """Reroute each perturbation but report exposure under the same reference field.

    Failures stay in the denominator. The first N serialized OD pairs define
    the subset; no fresh random sample is silently substituted. UTCI offsets
    and thresholds are applied to individual retained samples. Shade mixing is
    deterministic shrinkage toward 0.5, not a simulation of spatial shadow error.
    """
    if subset_size < 1:
        raise ValueError("subset_size must be positive")
    config.require_existing_inputs()
    if config.departure_time.utcoffset() is None:
        raise ValueError("Revision runs require an explicit departure_time UTC offset")
    ensure_output_layout(config)
    graph = load_experiment_graph(config)
    pairs = load_od_pairs(od_pairs_path, limit=subset_size)
    variants = sensitivity_variants() if variant_settings is None else variant_settings
    preference = get_method_config("proposed_full", comfort_threshold=config.comfort_threshold_c).preference
    context = build_real_feature_context(config)
    cache = {}
    rows = []
    hash_value = config_hash(config)
    try:
        for pair in pairs:
            origin = _coerce_node_id(graph, pair["origin_node"])
            destination = _coerce_node_id(graph, pair["destination_node"])
            baseline_distance = float(pair["baseline_shortest_distance_m"])
            for detour in config.detour_ratios:
                ceiling = baseline_distance * (1 + detour)
                reference = None
                reference_graph = None
                reference_error = None
                try:
                    reference_graph = _build_feature_graph_for_pair(
                        graph, origin, destination, ceiling, config=config, context=context,
                        cache=cache, sample_spacing_m=config.sample_spacing_m,
                        comfort_threshold=config.comfort_threshold_c,
                    )
                    reference, _ = route_with_method(
                        reference_graph, origin, destination, "proposed_full",
                        detour_ratio=detour, comfort_threshold=config.comfort_threshold_c,
                        maximum_distance_m=ceiling, departure_time=config.departure_time,
                        max_labels_per_node=config.route_search_labels_per_node,
                        max_expansions=config.route_search_expansions, max_seconds=config.route_search_seconds,
                    )
                except Exception as exc:
                    reference_error = exc
                for name, options in variants:
                    started = perf_counter()
                    extra = {"perturbation": json.dumps(options, sort_keys=True),
                             "reference_success": reference is not None,
                             "reference_heat_dose": reference.heat_dose if reference else None,
                             "reference_route_source": reference.route_source if reference else "",
                             "route_changed": None, "edge_jaccard_overlap": None,
                             "reference_H_minus_variant_H_K": None,
                             "variant_spacing_heat_dose": None}
                    try:
                        if reference_graph is None:
                            raise reference_error
                        spacing = options.get("spacing", config.sample_spacing_m)
                        featured = reference_graph
                        if spacing != config.sample_spacing_m:
                            featured = _build_feature_graph_for_pair(
                                graph, origin, destination, ceiling, config=config, context=context,
                                cache=cache, sample_spacing_m=spacing, comfort_threshold=config.comfort_threshold_c,
                            )
                        threshold = options.get("threshold", config.comfort_threshold_c)
                        projected = project_graph_for_method(
                            featured, "proposed_full", comfort_threshold=threshold,
                            utci_offset_c=options.get("utci_offset_c", 0),
                            shade_fraction_flip_rate=options.get("shade_mixing", 0),
                        )
                        selected, _ = route_with_method(
                            projected, origin, destination, "proposed_full", detour_ratio=detour,
                            comfort_threshold=threshold, maximum_distance_m=ceiling,
                            departure_time=config.departure_time,
                            preference_overrides=options.get("preference_overrides"),
                            max_labels_per_node=config.route_search_labels_per_node,
                            max_expansions=config.route_search_expansions, max_seconds=config.route_search_seconds,
                        )
                        # Fixed reporting inputs separate path changes from changes
                        # in the definition or sampling of the exposure measure.
                        candidate = _rescore_candidate_on_graph(
                            reference_graph, selected, preference,
                            departure_time=config.departure_time, utci_raster_path=None,
                        )
                        extra["variant_spacing_heat_dose"] = selected.heat_dose
                        if reference is not None:
                            extra.update(
                                route_changed=reference.edge_ids != candidate.edge_ids,
                                edge_jaccard_overlap=route_overlap_jaccard(reference.edge_ids, candidate.edge_ids),
                                reference_H_minus_variant_H_K=reference.heat_dose - candidate.heat_dose,
                            )
                        row = _candidate_row(
                            config, pair=pair, method=name, detour_ratio=detour, candidate=candidate,
                            baseline_distance_m=baseline_distance, runtime_ms=(perf_counter()-started)*1000,
                            success=True, failure_reason="", config_hash_value=hash_value, run_id=hash_value,
                        )
                    except Exception as exc:
                        row = _failure_row(
                            config, pair=pair, method=name, detour_ratio=detour,
                            baseline_distance_m=baseline_distance, runtime_ms=(perf_counter()-started)*1000,
                            failure_reason=str(exc), failure_type=type(exc).__name__,
                            config_hash_value=hash_value, run_id=hash_value,
                        )
                    rows.append(row | extra)
    finally:
        context.close()
    output = config.output_dir / "review_sensitivity_summary.csv"
    columns = ROUTE_SUMMARY_COLUMNS + list(extra)
    write_csv(output, rows, columns)
    write_json(config.output_dir / "review_sensitivity_protocol.json", {
        "variants": variants, "od_subset_size": len(pairs),
        "detour_ratios": config.detour_ratios, "reporting_threshold_c": config.comfort_threshold_c,
        "reporting_spacing_m": config.sample_spacing_m,
        "note": "All variant routes are rescored on the unperturbed reference feature graph. No field validation.",
    })
    return output

