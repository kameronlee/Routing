"""Experiment runners that adapt the existing routing engine to paper benchmarks."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Sequence

import networkx as nx

from routing_backend.baseline_methods import RouteMethod, available_methods, parse_method, route_with_method
from routing_backend.data_ingestion import apply_node_elevations_from_dem, clip_graph_to_detour_corridor, load_street_graph
from routing_backend.experiment_config import ExperimentConfig
from routing_backend.experiment_io import config_hash, ensure_output_layout, read_csv, write_csv, write_json, write_markdown
from routing_backend.microclimate_model import Coordinate
from routing_backend.real_features import RealFeatureContext, RealFeaturePaths
from routing_backend.result_metrics import excess_distance_ratio
from routing_backend.route_engine import RouteCandidate, build_feature_graph


ROUTE_SUMMARY_COLUMNS = [
    "study_name",
    "pair_id",
    "method",
    "detour_ratio",
    "origin_node",
    "destination_node",
    "baseline_shortest_distance_m",
    "route_distance_m",
    "excess_distance_m",
    "excess_distance_ratio",
    "duration_s",
    "mean_utci",
    "max_utci",
    "heat_dose",
    "shade_fraction",
    "sunlit_fraction",
    "scenic_score",
    "noise_score",
    "slope_penalty",
    "route_cost",
    "runtime_ms",
    "expanded_labels",
    "retained_labels",
    "success",
    "failure_reason",
    "raster_timestamp",
    "departure_time",
    "config_hash",
    "run_id",
    "edge_ids",
]


def load_od_pairs(path: str | Path, *, limit: int | None = None) -> list[dict[str, str]]:
    """Load benchmark OD pairs from CSV."""

    rows = read_csv(path)
    return rows[:limit] if limit is not None else rows


def build_real_feature_context(
    config: ExperimentConfig,
    *,
    use_shadow: bool = True,
    disabled_layers: Iterable[str] = (),
) -> RealFeatureContext:
    """Build a strict real-data feature context from experiment config paths."""

    paths = RealFeaturePaths(
        utci_raster=config.utci_raster_path,
        shadow_raster=config.shadow_raster_path if use_shadow else None,
        canopy_height_rasters=config.canopy_raster_paths,
        canopy_class_rasters=(),
        landcover_rasters=config.landcover_raster_paths,
        traffic_geojson=config.traffic_geojson_path,
        building_height_rasters=config.building_height_raster_paths,
    )
    return RealFeatureContext(paths, disabled_layers=disabled_layers)


def load_experiment_graph(config: ExperimentConfig) -> nx.MultiDiGraph:
    """Load the configured real street graph and apply DEM elevations when possible."""

    graph = load_street_graph(config.graph_path)
    return apply_node_elevations_from_dem(graph, config.dem_raster_path)


def run_route_benchmark(
    config: ExperimentConfig,
    *,
    od_pairs_path: str | Path,
    methods: Sequence[str] | None = None,
    limit: int | None = None,
    run_id: str | None = None,
) -> dict[str, Path]:
    """Run main method benchmark and write machine-readable outputs."""

    config.require_existing_inputs()
    ensure_output_layout(config)
    selected_methods = [parse_method(method) for method in (methods or available_methods())]
    pairs = load_od_pairs(od_pairs_path, limit=limit)
    graph = load_experiment_graph(config)
    run_identifier = run_id or config_hash(config)
    hash_value = config_hash(config)
    summary_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []
    geojson_features: list[dict[str, Any]] = []

    full_context = build_real_feature_context(config, use_shadow=True)
    azimuth_context = build_real_feature_context(config, use_shadow=False)
    full_cache: dict[tuple[Any, ...], Any] = {}
    azimuth_cache: dict[tuple[Any, ...], Any] = {}
    try:
        for pair in pairs:
            origin_node = _coerce_node_id(graph, pair["origin_node"])
            destination_node = _coerce_node_id(graph, pair["destination_node"])
            baseline_distance_m = float(pair["baseline_shortest_distance_m"])
            for detour_ratio in config.detour_ratios:
                for method in selected_methods:
                    context = azimuth_context if method == RouteMethod.AZIMUTH_HEURISTIC else full_context
                    cache = azimuth_cache if method == RouteMethod.AZIMUTH_HEURISTIC else full_cache
                    started = perf_counter()
                    try:
                        maximum_distance_m = baseline_distance_m * (1.0 + detour_ratio)
                        corridor_graph = clip_graph_to_detour_corridor(
                            graph,
                            origin_node,
                            destination_node,
                            maximum_distance_m=maximum_distance_m,
                        )
                        feature_graph = build_feature_graph(
                            corridor_graph,
                            departure_time=config.departure_time,
                            mode=config.mode,
                            sample_spacing_m=config.sample_spacing_m,
                            comfort_threshold=config.comfort_threshold_c,
                            utci_raster_path=config.utci_raster_path,
                            real_feature_context=context,
                            feature_cache=cache,
                        )
                        candidate, method_config = route_with_method(
                            feature_graph,
                            origin_node,
                            destination_node,
                            method,
                            detour_ratio=detour_ratio,
                            comfort_threshold=config.comfort_threshold_c,
                            departure_time=config.departure_time,
                            utci_raster_path=str(config.utci_raster_path),
                            max_labels_per_node=config.route_search_labels_per_node,
                            max_expansions=config.route_search_expansions,
                            max_seconds=config.route_search_seconds,
                        )
                        runtime_ms = (perf_counter() - started) * 1000.0
                        if method_config.enforce_detour and candidate.distance_m > maximum_distance_m + 1e-6:
                            raise RuntimeError(
                                "Route exceeded explicit detour budget: "
                                f"{candidate.distance_m:.2f} m > {maximum_distance_m:.2f} m"
                            )
                        row = _candidate_row(
                            config,
                            pair=pair,
                            method=method.value,
                            detour_ratio=detour_ratio,
                            candidate=candidate,
                            baseline_distance_m=baseline_distance_m,
                            runtime_ms=runtime_ms,
                            success=True,
                            failure_reason="",
                            config_hash_value=hash_value,
                            run_id=run_identifier,
                        )
                        summary_rows.append(row)
                        geojson_features.append(_candidate_geojson_feature(row, candidate.geometry))
                    except Exception as exc:
                        runtime_ms = (perf_counter() - started) * 1000.0
                        row = _failure_row(
                            config,
                            pair=pair,
                            method=method.value,
                            detour_ratio=detour_ratio,
                            baseline_distance_m=baseline_distance_m,
                            runtime_ms=runtime_ms,
                            failure_reason=str(exc),
                            config_hash_value=hash_value,
                            run_id=run_identifier,
                        )
                        summary_rows.append(row)
                        failure_rows.append(row)
    finally:
        full_context.close()
        azimuth_context.close()

    outputs = {
        "routes_summary": config.output_dir / "routes_summary.csv",
        "routes_geojson": config.output_dir / "routes.geojson",
        "benchmark_failures": config.output_dir / "benchmark_failures.csv",
        "benchmark_report": config.output_dir / "benchmark_report.md",
    }
    write_csv(outputs["routes_summary"], summary_rows, ROUTE_SUMMARY_COLUMNS)
    write_csv(outputs["benchmark_failures"], failure_rows, ROUTE_SUMMARY_COLUMNS)
    write_json(outputs["routes_geojson"], {"type": "FeatureCollection", "features": geojson_features})
    write_markdown(outputs["benchmark_report"], _benchmark_report(config, summary_rows, failure_rows, selected_methods))
    return outputs


def run_ablation_benchmark(
    config: ExperimentConfig,
    *,
    od_pairs_path: str | Path,
    limit: int | None = None,
    detour_ratio: float | None = None,
    run_id: str | None = None,
) -> dict[str, Path]:
    """Run configured ablation variants against the strict real-data bundle."""

    config.require_existing_inputs()
    ensure_output_layout(config)
    pairs = load_od_pairs(od_pairs_path, limit=limit)
    graph = load_experiment_graph(config)
    run_identifier = run_id or config_hash(config)
    hash_value = config_hash(config)
    selected_detour = detour_ratio if detour_ratio is not None else max(config.detour_ratios)
    rows: list[dict[str, Any]] = []
    variants = [
        ("shortest_distance", RouteMethod.SHORTEST_DISTANCE, True, (), {}),
        ("full_model", RouteMethod.PROPOSED_FULL, True, (), {}),
        ("no_utci_raster", RouteMethod.PROPOSED_FULL, True, (), {"disable_utci": True}),
        ("no_shadow_raster", RouteMethod.PROPOSED_FULL, False, (), {}),
        ("azimuth_only", RouteMethod.AZIMUTH_HEURISTIC, False, (), {}),
        ("no_canopy", RouteMethod.PROPOSED_FULL, True, ("canopy",), {}),
        ("no_building_height", RouteMethod.PROPOSED_FULL, False, ("building_height",), {}),
        ("no_traffic_noise", RouteMethod.PROPOSED_FULL, True, (), {"disable_noise": True}),
        ("no_scenic", RouteMethod.PROPOSED_FULL, True, (), {"disable_scenic": True}),
        ("no_uncertainty_penalty", RouteMethod.PROPOSED_FULL, True, (), {"disable_uncertainty": True}),
        ("mean_utci_only", RouteMethod.MEAN_UTCI, True, (), {}),
        ("heat_dose_only", RouteMethod.HEAT_DOSE, True, (), {}),
        ("shade_only", RouteMethod.SHADOW_ONLY, True, (), {}),
    ]
    contexts: dict[tuple[bool, tuple[str, ...]], RealFeatureContext] = {}
    caches: dict[tuple[bool, tuple[str, ...]], dict[tuple[Any, ...], Any]] = {}

    def context_for(
        use_shadow: bool,
        disabled_layers: Sequence[str],
    ) -> tuple[RealFeatureContext, dict[tuple[Any, ...], Any]]:
        key = (use_shadow, tuple(sorted(disabled_layers)))
        if key not in contexts:
            contexts[key] = build_real_feature_context(
                config,
                use_shadow=use_shadow,
                disabled_layers=key[1],
            )
            caches[key] = {}
        return contexts[key], caches[key]

    try:
        for pair in pairs:
            origin_node = _coerce_node_id(graph, pair["origin_node"])
            destination_node = _coerce_node_id(graph, pair["destination_node"])
            baseline_distance_m = float(pair["baseline_shortest_distance_m"])
            maximum_distance_m = baseline_distance_m * (1.0 + selected_detour)
            for ablation_name, method, use_shadow, disabled_layers, perturbations in variants:
                started = perf_counter()
                try:
                    context, cache = context_for(use_shadow, disabled_layers)
                    corridor_graph = clip_graph_to_detour_corridor(
                        graph,
                        origin_node,
                        destination_node,
                        maximum_distance_m=maximum_distance_m,
                    )
                    feature_graph = build_feature_graph(
                        corridor_graph,
                        departure_time=config.departure_time,
                        mode=config.mode,
                        sample_spacing_m=config.sample_spacing_m,
                        comfort_threshold=config.comfort_threshold_c,
                        utci_raster_path=config.utci_raster_path,
                        real_feature_context=context,
                        feature_cache=cache,
                    )
                    if perturbations:
                        from routing_backend.baseline_methods import project_graph_for_method

                        feature_graph = project_graph_for_method(
                            feature_graph,
                            RouteMethod.PROPOSED_FULL,
                            comfort_threshold=config.comfort_threshold_c,
                            **perturbations,
                        )
                    candidate, _method_config = route_with_method(
                        feature_graph,
                        origin_node,
                        destination_node,
                        method,
                        detour_ratio=selected_detour,
                        comfort_threshold=config.comfort_threshold_c,
                        departure_time=config.departure_time,
                        utci_raster_path=str(config.utci_raster_path),
                        max_labels_per_node=config.route_search_labels_per_node,
                        max_expansions=config.route_search_expansions,
                        max_seconds=config.route_search_seconds,
                    )
                    runtime_ms = (perf_counter() - started) * 1000.0
                    row = _candidate_row(
                        config,
                        pair=pair,
                        method=ablation_name,
                        detour_ratio=selected_detour,
                        candidate=candidate,
                        baseline_distance_m=baseline_distance_m,
                        runtime_ms=runtime_ms,
                        success=True,
                        failure_reason="",
                        config_hash_value=hash_value,
                        run_id=run_identifier,
                    )
                    rows.append(row)
                except Exception as exc:
                    rows.append(
                        _failure_row(
                            config,
                            pair=pair,
                            method=ablation_name,
                            detour_ratio=selected_detour,
                            baseline_distance_m=baseline_distance_m,
                            runtime_ms=(perf_counter() - started) * 1000.0,
                            failure_reason=str(exc),
                            config_hash_value=hash_value,
                            run_id=run_identifier,
                        )
                    )
    finally:
        for context in contexts.values():
            context.close()

    outputs = {
        "ablations_summary": config.output_dir / "ablations_summary.csv",
        "ablation_report": config.output_dir / "ablation_report.md",
    }
    write_csv(outputs["ablations_summary"], rows, ROUTE_SUMMARY_COLUMNS)
    write_markdown(outputs["ablation_report"], _ablation_report(config, rows))
    return outputs


def run_sensitivity_benchmark(
    config: ExperimentConfig,
    *,
    od_pairs_path: str | Path,
    subset_size: int = 200,
    detour_ratio: float | None = None,
    run_id: str | None = None,
) -> dict[str, Path]:
    """Run lightweight robustness checks over perturbations of featured edges."""

    from routing_backend.baseline_methods import project_graph_for_method
    from routing_backend.result_metrics import route_overlap_jaccard

    config.require_existing_inputs()
    ensure_output_layout(config)
    pairs = load_od_pairs(od_pairs_path, limit=subset_size)
    graph = load_experiment_graph(config)
    run_identifier = run_id or config_hash(config)
    hash_value = config_hash(config)
    selected_detour = detour_ratio if detour_ratio is not None else max(config.detour_ratios)
    perturbations: list[tuple[str, dict[str, Any]]] = []
    perturbations.extend((f"utci_offset_{offset:+g}c", {"utci_offset_c": float(offset)}) for offset in [-3, -2, -1, 1, 2, 3])
    perturbations.extend((f"comfort_threshold_{threshold:g}c", {"comfort_threshold": float(threshold)}) for threshold in [24, 26, 28, 30])
    perturbations.extend(
        (f"shadow_noise_{int(rate * 100)}pct", {"shade_fraction_flip_rate": rate}) for rate in [0.01, 0.05, 0.10]
    )
    perturbations.extend(
        [
            ("weights_cool_heavy", {"method": RouteMethod.HEAT_DOSE}),
            ("weights_distance_heavy", {"method": RouteMethod.SHORTEST_DISTANCE}),
            ("weights_shade_heavy", {"method": RouteMethod.SHADOW_ONLY}),
            ("weights_balanced", {"method": RouteMethod.PROPOSED_FULL}),
        ]
    )
    perturbations.extend((f"sampling_spacing_{spacing:g}m", {"sample_spacing_m": float(spacing)}) for spacing in [10, 20, 40, 60])

    rows: list[dict[str, Any]] = []
    context = build_real_feature_context(config, use_shadow=True)
    cache: dict[tuple[Any, ...], Any] = {}
    try:
        for pair in pairs:
            origin_node = _coerce_node_id(graph, pair["origin_node"])
            destination_node = _coerce_node_id(graph, pair["destination_node"])
            baseline_distance_m = float(pair["baseline_shortest_distance_m"])
            maximum_distance_m = baseline_distance_m * (1.0 + selected_detour)
            base_graph = _build_feature_graph_for_pair(
                graph,
                origin_node,
                destination_node,
                maximum_distance_m,
                config=config,
                context=context,
                cache=cache,
                sample_spacing_m=config.sample_spacing_m,
                comfort_threshold=config.comfort_threshold_c,
            )
            base_candidate, _ = route_with_method(
                base_graph,
                origin_node,
                destination_node,
                RouteMethod.PROPOSED_FULL,
                detour_ratio=selected_detour,
                comfort_threshold=config.comfort_threshold_c,
                departure_time=config.departure_time,
                utci_raster_path=str(config.utci_raster_path),
                max_labels_per_node=config.route_search_labels_per_node,
                max_expansions=config.route_search_expansions,
                max_seconds=config.route_search_seconds,
            )
            for perturbation_name, options in perturbations:
                started = perf_counter()
                try:
                    comfort_threshold = float(options.get("comfort_threshold", config.comfort_threshold_c))
                    method = options.get("method", RouteMethod.PROPOSED_FULL)
                    sample_spacing_m = float(options.get("sample_spacing_m", config.sample_spacing_m))
                    if sample_spacing_m != config.sample_spacing_m:
                        feature_graph = _build_feature_graph_for_pair(
                            graph,
                            origin_node,
                            destination_node,
                            maximum_distance_m,
                            config=config,
                            context=context,
                            cache=cache,
                            sample_spacing_m=sample_spacing_m,
                            comfort_threshold=comfort_threshold,
                        )
                    else:
                        feature_graph = base_graph
                    feature_graph = project_graph_for_method(
                        feature_graph,
                        method,
                        comfort_threshold=comfort_threshold,
                        utci_offset_c=float(options.get("utci_offset_c", 0.0)),
                        shade_fraction_flip_rate=float(options.get("shade_fraction_flip_rate", 0.0)),
                    )
                    candidate, _ = route_with_method(
                        feature_graph,
                        origin_node,
                        destination_node,
                        method,
                        detour_ratio=selected_detour,
                        comfort_threshold=comfort_threshold,
                        departure_time=config.departure_time,
                        utci_raster_path=str(config.utci_raster_path),
                        max_labels_per_node=config.route_search_labels_per_node,
                        max_expansions=config.route_search_expansions,
                        max_seconds=config.route_search_seconds,
                    )
                    overlap = route_overlap_jaccard(base_candidate.edge_ids, candidate.edge_ids)
                    rows.append(
                        _candidate_row(
                            config,
                            pair=pair,
                            method=perturbation_name,
                            detour_ratio=selected_detour,
                            candidate=candidate,
                            baseline_distance_m=baseline_distance_m,
                            runtime_ms=(perf_counter() - started) * 1000.0,
                            success=True,
                            failure_reason="",
                            config_hash_value=hash_value,
                            run_id=run_identifier,
                        )
                        | {
                            "route_changed": str(base_candidate.edge_ids != candidate.edge_ids).lower(),
                            "edge_jaccard_overlap": overlap,
                            "base_proposed_heat_dose": base_candidate.heat_dose,
                            "base_proposed_mean_utci": base_candidate.mean_utci,
                            "base_proposed_max_utci": base_candidate.max_utci,
                        }
                    )
                except Exception as exc:
                    rows.append(
                        _failure_row(
                            config,
                            pair=pair,
                            method=perturbation_name,
                            detour_ratio=selected_detour,
                            baseline_distance_m=baseline_distance_m,
                            runtime_ms=(perf_counter() - started) * 1000.0,
                            failure_reason=str(exc),
                            config_hash_value=hash_value,
                            run_id=run_identifier,
                        )
                        | {
                            "route_changed": "",
                            "edge_jaccard_overlap": "",
                            "base_proposed_heat_dose": "",
                            "base_proposed_mean_utci": "",
                            "base_proposed_max_utci": "",
                        }
                    )
    finally:
        context.close()

    outputs = {
        "sensitivity_summary": config.output_dir / "sensitivity_summary.csv",
        "sensitivity_report": config.output_dir / "sensitivity_report.md",
    }
    columns = ROUTE_SUMMARY_COLUMNS + [
        "route_changed",
        "edge_jaccard_overlap",
        "base_proposed_heat_dose",
        "base_proposed_mean_utci",
        "base_proposed_max_utci",
    ]
    write_csv(outputs["sensitivity_summary"], rows, columns)
    write_markdown(outputs["sensitivity_report"], _sensitivity_report(config, rows))
    return outputs


def _build_feature_graph_for_pair(
    graph: nx.MultiDiGraph,
    origin_node: Any,
    destination_node: Any,
    maximum_distance_m: float,
    *,
    config: ExperimentConfig,
    context: RealFeatureContext,
    cache: dict[tuple[Any, ...], Any],
    sample_spacing_m: float,
    comfort_threshold: float,
) -> nx.MultiDiGraph:
    corridor_graph = clip_graph_to_detour_corridor(
        graph,
        origin_node,
        destination_node,
        maximum_distance_m=maximum_distance_m,
    )
    return build_feature_graph(
        corridor_graph,
        departure_time=config.departure_time,
        mode=config.mode,
        sample_spacing_m=sample_spacing_m,
        comfort_threshold=comfort_threshold,
        utci_raster_path=config.utci_raster_path,
        real_feature_context=context,
        feature_cache=cache,
    )


def _coerce_node_id(graph: nx.Graph, value: str) -> Any:
    if value in graph:
        return value
    for node in graph.nodes:
        if str(node) == str(value):
            return node
    return value


def _candidate_row(
    config: ExperimentConfig,
    *,
    pair: dict[str, str],
    method: str,
    detour_ratio: float,
    candidate: RouteCandidate,
    baseline_distance_m: float,
    runtime_ms: float,
    success: bool,
    failure_reason: str,
    config_hash_value: str,
    run_id: str,
) -> dict[str, Any]:
    excess_ratio = excess_distance_ratio(candidate.distance_m, baseline_distance_m)
    return {
        "study_name": config.study_name,
        "pair_id": pair["pair_id"],
        "method": method,
        "detour_ratio": detour_ratio,
        "origin_node": pair["origin_node"],
        "destination_node": pair["destination_node"],
        "baseline_shortest_distance_m": baseline_distance_m,
        "route_distance_m": candidate.distance_m,
        "excess_distance_m": candidate.distance_m - baseline_distance_m,
        "excess_distance_ratio": excess_ratio,
        "duration_s": candidate.duration_s,
        "mean_utci": candidate.mean_utci,
        "max_utci": candidate.max_utci,
        "heat_dose": candidate.heat_dose,
        "shade_fraction": candidate.shade_fraction,
        "sunlit_fraction": 1.0 - candidate.shade_fraction,
        "scenic_score": candidate.scenic_score,
        "noise_score": candidate.noise_score,
        "slope_penalty": candidate.slope_penalty,
        "route_cost": candidate.cost,
        "runtime_ms": runtime_ms,
        "expanded_labels": "",
        "retained_labels": "",
        "success": success,
        "failure_reason": failure_reason,
        "raster_timestamp": config.departure_time.isoformat(),
        "departure_time": config.departure_time.isoformat(),
        "config_hash": config_hash_value,
        "run_id": run_id,
        "edge_ids": json.dumps(candidate.edge_ids),
    }


def _failure_row(
    config: ExperimentConfig,
    *,
    pair: dict[str, str],
    method: str,
    detour_ratio: float,
    baseline_distance_m: float,
    runtime_ms: float,
    failure_reason: str,
    config_hash_value: str,
    run_id: str,
) -> dict[str, Any]:
    return {
        "study_name": config.study_name,
        "pair_id": pair.get("pair_id", ""),
        "method": method,
        "detour_ratio": detour_ratio,
        "origin_node": pair.get("origin_node", ""),
        "destination_node": pair.get("destination_node", ""),
        "baseline_shortest_distance_m": baseline_distance_m,
        "route_distance_m": "",
        "excess_distance_m": "",
        "excess_distance_ratio": "",
        "duration_s": "",
        "mean_utci": "",
        "max_utci": "",
        "heat_dose": "",
        "shade_fraction": "",
        "sunlit_fraction": "",
        "scenic_score": "",
        "noise_score": "",
        "slope_penalty": "",
        "route_cost": "",
        "runtime_ms": runtime_ms,
        "expanded_labels": "",
        "retained_labels": "",
        "success": False,
        "failure_reason": failure_reason,
        "raster_timestamp": config.departure_time.isoformat(),
        "departure_time": config.departure_time.isoformat(),
        "config_hash": config_hash_value,
        "run_id": run_id,
        "edge_ids": "",
    }


def _candidate_geojson_feature(row: dict[str, Any], geometry: Sequence[Coordinate]) -> dict[str, Any]:
    properties = {key: value for key, value in row.items() if key != "edge_ids"}
    properties["edge_ids"] = row.get("edge_ids", "")
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon, lat] for lat, lon in geometry],
        },
    }


def _benchmark_report(
    config: ExperimentConfig,
    rows: Iterable[dict[str, Any]],
    failures: Iterable[dict[str, Any]],
    methods: Sequence[RouteMethod],
) -> str:
    row_list = list(rows)
    failure_list = list(failures)
    success_count = sum(1 for row in row_list if str(row.get("success")).lower() in {"true", "1"})
    return f"""# Benchmark Report: {config.study_name}

This computational benchmark uses modeled UTCI and direct-shadow rasters for a single snapshot. It does not report field-validated pedestrian comfort.

- Departure time: `{config.departure_time.isoformat()}`
- Methods: {", ".join(method.value for method in methods)}
- OD rows attempted: {len(row_list)}
- Successful route rows: {success_count}
- Failed route rows: {len(failure_list)}
- Detour ratios: {", ".join(str(value) for value in config.detour_ratios)}

Failures, if any, are recorded in `benchmark_failures.csv`.
"""


def _ablation_report(config: ExperimentConfig, rows: Iterable[dict[str, Any]]) -> str:
    row_list = list(rows)
    success_count = sum(1 for row in row_list if str(row.get("success")).lower() in {"true", "1"})
    failure_count = len(row_list) - success_count
    return f"""# Ablation Report: {config.study_name}

The ablation experiment is computational and raster-backed. Layer-disabled variants use the same real input bundle while neutralizing the requested feature channel; no synthetic microclimate data is introduced.

- Rows written: {len(row_list)}
- Successful rows: {success_count}
- Failed rows: {failure_count}

The `no_canopy` and `no_building_height` variants disable those feature joins for routing. UTCI and direct-shadow rasters remain the configured modeled scene products.
"""


def _sensitivity_report(config: ExperimentConfig, rows: Iterable[dict[str, Any]]) -> str:
    row_list = list(rows)
    success_count = sum(1 for row in row_list if str(row.get("success")).lower() in {"true", "1"})
    return f"""# Sensitivity Report: {config.study_name}

This report summarizes robustness checks from perturbing modeled edge features and rerunning the constrained route search. It is not field validation.

- Rows written: {len(row_list)}
- Successful rows: {success_count}
- Departure time: `{config.departure_time.isoformat()}`
"""
