"""FastAPI application for radiative-perceptual routing."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import threading
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from routing_backend.data_ingestion import (
    apply_node_elevations_from_dem,
    build_synthetic_graph,
    clip_graph_to_detour_corridor,
    clip_graph_to_candidate_paths,
    clip_graph_to_route_area,
    download_osm_graph,
    load_street_graph,
    nearest_node,
)
from routing_backend.microclimate_model import Coordinate
from routing_backend.microclimate_model import haversine_distance_m
from routing_backend.preferences import Preference, preference_from_descriptors
from routing_backend.raster_data import (
    default_data_dir,
    default_dem_path,
    find_time_raster,
    raster_timestamp,
    sample_raster_values,
)
from routing_backend.real_features import RealDataMissingError, RealFeatureContext, discover_real_feature_paths
from routing_backend.route_engine import (
    RouteCandidate,
    baseline_shortest_path_distance,
    build_feature_graph,
    length_shortest_route_candidate,
    node_path_candidate,
    resource_constrained_routes,
)


def _cors_origins_from_env(value: str | None) -> tuple[str, ...]:
    """Parse a comma-separated CORS origin list for browser-based Expo clients."""

    if not value:
        return ("*",)
    origins = tuple(origin.strip() for origin in value.split(",") if origin.strip())
    return origins or ("*",)


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    default_city: str | None = None
    default_network_type: str = "walk"
    data_dir: Path = default_data_dir()
    prefer_local_data: bool = True
    route_clip_buffer_m: float = 500.0
    detour_corridor_margin_m: float = 50.0
    edge_sample_spacing_m: float = 60.0
    snap_warning_threshold_m: float = 50.0
    max_snap_distance_m: float = 250.0
    route_search_seconds: float = 1.5
    route_search_expansions: int = 20_000
    route_search_labels_per_node: int = 8
    route_candidate_path_limit: int = 10
    allow_synthetic_graph: bool = False
    allow_synthetic_microclimate: bool = False
    cors_origins: tuple[str, ...] = ("*",)
    preload_local_graph: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from environment variables."""

        return cls(
            default_city=os.getenv("ROUTING_DEFAULT_CITY"),
            default_network_type=os.getenv("ROUTING_NETWORK_TYPE", "walk"),
            data_dir=Path(os.getenv("ROUTING_DATA_DIR", str(default_data_dir()))),
            prefer_local_data=os.getenv("ROUTING_PREFER_LOCAL_DATA", "1") != "0",
            route_clip_buffer_m=float(os.getenv("ROUTING_ROUTE_CLIP_BUFFER_M", "500")),
            detour_corridor_margin_m=float(os.getenv("ROUTING_DETOUR_CORRIDOR_MARGIN_M", "50")),
            edge_sample_spacing_m=float(os.getenv("ROUTING_EDGE_SAMPLE_SPACING_M", "60")),
            snap_warning_threshold_m=float(os.getenv("ROUTING_SNAP_WARNING_THRESHOLD_M", "50")),
            max_snap_distance_m=float(os.getenv("ROUTING_MAX_SNAP_DISTANCE_M", "250")),
            route_search_seconds=float(os.getenv("ROUTING_ROUTE_SEARCH_SECONDS", "1.5")),
            route_search_expansions=int(os.getenv("ROUTING_ROUTE_SEARCH_EXPANSIONS", "20000")),
            route_search_labels_per_node=int(os.getenv("ROUTING_ROUTE_SEARCH_LABELS_PER_NODE", "8")),
            route_candidate_path_limit=int(os.getenv("ROUTING_ROUTE_CANDIDATE_PATH_LIMIT", "10")),
            allow_synthetic_graph=os.getenv("ROUTING_ALLOW_SYNTHETIC_GRAPH", "0") == "1",
            allow_synthetic_microclimate=os.getenv("ROUTING_ALLOW_SYNTHETIC_MICROCLIMATE", "0") == "1",
            cors_origins=_cors_origins_from_env(os.getenv("ROUTING_CORS_ORIGINS")),
            preload_local_graph=os.getenv("ROUTING_PRELOAD_LOCAL_GRAPH", "1") != "0",
        )


class CoordinateModel(BaseModel):
    """Latitude/longitude coordinate in decimal degrees."""

    lat: float = Field(..., ge=-90, le=90, description="Latitude in decimal degrees.")
    lon: float = Field(..., ge=-180, le=180, description="Longitude in decimal degrees.")

    def as_tuple(self) -> Coordinate:
        return self.lat, self.lon


class PreferenceWeights(BaseModel):
    """Optional explicit preference weights overriding descriptor defaults."""

    weight_cool: float | None = Field(None, ge=0)
    weight_scenic: float | None = Field(None, ge=0)
    weight_quiet: float | None = Field(None, ge=0)
    weight_slope: float | None = Field(None, ge=0)
    weight_time: float | None = Field(None, ge=0)
    weight_distance: float | None = Field(None, ge=0)
    uncertainty_penalty: float | None = Field(None, ge=0)
    comfort_threshold: float | None = Field(None, description="UTCI comfort threshold in degrees C.")


class RouteRequest(BaseModel):
    """Request body for query-conditioned route search."""

    origin: CoordinateModel
    destination: CoordinateModel
    departure_time: datetime | None = Field(
        None,
        description="Local departure time. Defaults to the current server time when omitted.",
    )
    city: str | None = Field(
        None,
        description="Optional OSMnx place name used only when no local graph is available.",
    )
    mode: Literal["walk", "bike", "cycle", "cycling"] = Field("walk", description="Travel mode.")
    objective: Literal["comfort", "shortest"] = Field(
        "comfort",
        description="Use comfort for radiative-perceptual routing or shortest for a true length-shortest baseline.",
    )
    descriptors: list[str] = Field(
        default_factory=list,
        description='High-level preference descriptors such as "heat sensitive" or "noise averse".',
    )
    weights: PreferenceWeights | None = Field(None, description="Explicit weight overrides.")
    detour_ratio: float = Field(
        0.20,
        ge=0,
        le=2,
        description="Maximum extra distance relative to the shortest path, e.g. 0.2 for 20%.",
    )
    max_candidates: int = Field(3, ge=1, le=5, description="Maximum number of route candidates.")
    snap_tolerance_m: float | None = Field(
        None,
        ge=250,
        le=400,
        description=(
            "Optional bounded snap tolerance for large landmarks or parks. "
            "Ordinary addresses should omit this and use the server default."
        ),
    )


class RouteCandidateResponse(BaseModel):
    """Response payload for one candidate route."""

    geometry: list[CoordinateModel]
    edge_ids: list[str]
    distance_m: float
    duration_s: float
    mean_utci: float
    max_utci: float
    heat_dose: float
    shade_fraction: float
    scenic_score: float
    noise_score: float
    slope_penalty: float
    cost: float
    route_source: str = "unknown"
    search_truncated: bool = False
    maximum_distance_m: float | None = None
    shade_fallback_fraction: float | None = None


class RouteResponse(BaseModel):
    """Route search response with selected graph metadata."""

    graph_source: str
    origin_node: str
    destination_node: str
    origin_snap_distance_m: float
    destination_snap_distance_m: float
    removed_no_utci_edges: int = 0
    utci_source: str | None = None
    utci_time: datetime | None = None
    requested_departure_time: datetime
    uses_nearest_time: bool = False
    search_truncated: bool = False
    warnings: list[str] = Field(default_factory=list)
    candidates: list[RouteCandidateResponse]


class UtciTileResponse(BaseModel):
    """Small real UTCI tile sampled from the selected SOLWEIG GeoTIFF."""

    center: CoordinateModel
    time: datetime | None
    requested_time: datetime | None = None
    utci_source: str
    values: list[dict[str, float]]
    min_utci: float
    mean_utci: float
    max_utci: float


class DataStatusResponse(BaseModel):
    """Current local data bundle status."""

    data_dir: str
    manifest_exists: bool
    graph_exists: bool
    dem_exists: bool
    utci_raster: str | None
    shadow_raster: str | None = None
    graph_path: str | None
    dem_path: str | None
    manifest_aoi: str | None = None
    manifest_created_at: str | None = None
    canopy_raster_count: int = 0
    landcover_raster_count: int = 0
    lidar_tiles_downloaded: int = 0
    lidar_tiles_processed: int | None = None
    traffic_exists: bool = False
    direct_shadow_ready: bool = False
    strict_real_ready: bool = False
    missing_required_layers: list[str] = Field(default_factory=list)


def _preference_from_request(request: RouteRequest) -> Preference:
    preference = preference_from_descriptors(request.descriptors)
    if request.weights is None:
        return preference
    return preference.with_overrides(**request.weights.model_dump(exclude_none=True))


def _candidate_to_response(candidate: RouteCandidate) -> RouteCandidateResponse:
    return RouteCandidateResponse(
        geometry=[CoordinateModel(lat=lat, lon=lon) for lat, lon in candidate.geometry],
        edge_ids=candidate.edge_ids,
        distance_m=candidate.distance_m,
        duration_s=candidate.duration_s,
        mean_utci=candidate.mean_utci,
        max_utci=candidate.max_utci,
        heat_dose=candidate.heat_dose,
        shade_fraction=candidate.shade_fraction,
        scenic_score=candidate.scenic_score,
        noise_score=candidate.noise_score,
        slope_penalty=candidate.slope_penalty,
        cost=candidate.cost,
        route_source=candidate.route_source,
        search_truncated=candidate.search_truncated,
        maximum_distance_m=candidate.maximum_distance_m,
        shade_fallback_fraction=candidate.shade_fallback_fraction,
    )


def _local_graph_path(settings: Settings, mode: str) -> Path | None:
    network = "bike" if mode in {"bike", "cycle", "cycling"} else "walk"
    candidates = [
        settings.data_dir / "processed" / "streets" / f"dc_{network}_graph.graphml",
        settings.data_dir / "processed" / "streets" / "dc_walk_graph.graphml",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _looks_like_dc_request(origin: CoordinateModel, destination: CoordinateModel, city: str | None) -> bool:
    if city:
        normalized_city = city.lower()
        # An explicit/default DC city should always use the installed graph. The
        # snap-distance check below then rejects out-of-coverage coordinates
        # immediately instead of attempting a slow OSM network download.
        return "washington" in normalized_city or "district of columbia" in normalized_city
    for coordinate in (origin, destination):
        if not (38.75 <= coordinate.lat <= 39.05 and -77.20 <= coordinate.lon <= -76.85):
            return False
    return True


def _load_cached_graph(app: FastAPI, graph_path: Path):
    with app.state.graph_cache_lock:
        cache = getattr(app.state, "graph_cache", {})
        key = str(graph_path)
        if key not in cache:
            cache[key] = load_street_graph(graph_path)
            app.state.graph_cache = cache
        return cache[key]


def _load_cached_elevated_graph(app: FastAPI, graph_path: Path, dem_path: Path):
    with app.state.graph_cache_lock:
        cache = getattr(app.state, "elevated_graph_cache", {})
        key = f"{graph_path}|{dem_path}"
        if key not in cache:
            cache[key] = apply_node_elevations_from_dem(_load_cached_graph(app, graph_path), dem_path)
            app.state.elevated_graph_cache = cache
        return cache[key]


def _preload_local_graph(app: FastAPI, settings: Settings) -> None:
    if not settings.prefer_local_data:
        return
    graph_path = _local_graph_path(settings, "walk")
    dem_path = default_dem_path(settings.data_dir)
    if graph_path is not None and dem_path is not None:
        _load_cached_elevated_graph(app, graph_path, dem_path)


def _node_coordinate(graph, node) -> Coordinate:
    data = graph.nodes[node]
    return float(data["y"]), float(data["x"])


def _snap_warnings(
    *,
    origin_snap_distance_m: float,
    destination_snap_distance_m: float,
    threshold_m: float,
) -> list[str]:
    warnings: list[str] = []
    if origin_snap_distance_m > threshold_m:
        warnings.append(f"Origin snapped {origin_snap_distance_m:.1f} m to the nearest graph node.")
    if destination_snap_distance_m > threshold_m:
        warnings.append(f"Destination snapped {destination_snap_distance_m:.1f} m to the nearest graph node.")
    return warnings


def _nearest_route_nodes(graph, origin: CoordinateModel, destination: CoordinateModel):
    origin_node = nearest_node(graph, origin.as_tuple())
    destination_node = nearest_node(graph, destination.as_tuple())
    origin_distance = haversine_distance_m(origin.as_tuple(), _node_coordinate(graph, origin_node))
    destination_distance = haversine_distance_m(destination.as_tuple(), _node_coordinate(graph, destination_node))
    return origin_node, destination_node, origin_distance, destination_distance


def _is_shortest_request(request: RouteRequest) -> bool:
    descriptors = {descriptor.strip().lower() for descriptor in request.descriptors}
    return request.objective == "shortest" or bool(descriptors & {"shortest", "fastest"})


def _rank_single_priority_candidates(
    request: RouteRequest,
    candidates: list[RouteCandidate],
) -> list[RouteCandidate] | None:
    """Rank single-purpose profiles by the metric users explicitly selected."""

    descriptors = {descriptor.strip().lower() for descriptor in request.descriptors}
    heat = bool(descriptors & {"heat sensitive", "avoid heat", "coolest", "shade", "shade seeker"})
    scenic = bool(descriptors & {"scenic", "green", "greenery", "pleasant", "park lover"})
    quiet = bool(descriptors & {"noise averse", "quiet", "quietest", "low noise"})
    hills = bool(descriptors & {"avoid hills", "mobility limited", "flat", "low slope"})
    selected = sum((heat, scenic, quiet, hills))
    if selected != 1:
        return None
    if scenic:
        return sorted(candidates, key=lambda candidate: (-candidate.scenic_score, candidate.distance_m))
    if quiet:
        return sorted(candidates, key=lambda candidate: (candidate.noise_score, candidate.distance_m))
    if hills:
        return sorted(candidates, key=lambda candidate: (candidate.slope_penalty, candidate.distance_m))
    return sorted(
        candidates,
        key=lambda candidate: (candidate.mean_utci, candidate.max_utci, -candidate.shade_fraction, candidate.distance_m),
    )


def build_data_status(settings: Settings | None = None) -> DataStatusResponse:
    """Report which local real-data bundle assets are available."""

    app_settings = settings or Settings.from_env()
    graph_path = _local_graph_path(app_settings, "walk")
    dem_path = default_dem_path(app_settings.data_dir)
    utci_raster = find_time_raster(app_settings.data_dir, "utci", datetime.now())
    shadow_raster = find_time_raster(app_settings.data_dir, "shadow", datetime.now())
    traffic_path = app_settings.data_dir / "raw" / "traffic_noise" / "ddot_traffic_volume_2023.geojson"
    canopy_rasters = [
        path
        for path in [
            app_settings.data_dir / "processed" / "rasters" / "canopy_height_1m.tif",
            app_settings.data_dir / "processed" / "rasters" / "canopy_1m.tif",
            app_settings.data_dir / "processed" / "rasters" / "canopy_1m_center_tile.tif",
            app_settings.data_dir / "processed" / "solweig_inputs" / "trees_cdsm_1m.tif",
            app_settings.data_dir / "processed" / "solweig_inputs" / "trees_cdsm_1m_center_tile.tif",
        ]
        if path.exists()
    ]
    landcover_rasters = [
        path
        for path in [
            app_settings.data_dir / "processed" / "rasters" / "landcover_1m.tif",
            app_settings.data_dir / "processed" / "rasters" / "landcover_1m_center_tile.tif",
            app_settings.data_dir / "processed" / "solweig_inputs" / "landcover_1m.tif",
            app_settings.data_dir / "processed" / "solweig_inputs" / "landcover_1m_center_tile.tif",
        ]
        if path.exists()
    ]
    missing = []
    if graph_path is None:
        missing.append("local DC walking GraphML")
    if dem_path is None:
        missing.append("LiDAR-derived DEM")
    if utci_raster is None:
        missing.append("SOLWEIG UTCI raster")
    if not canopy_rasters:
        missing.append("tree canopy or canopy-height raster")
    if not traffic_path.exists():
        missing.append("DDOT traffic volume GeoJSON")
    manifest_path = app_settings.data_dir / "metadata" / "manifest.json"
    lidar_manifest_path = app_settings.data_dir / "metadata" / "lidar_processing_manifest.json"
    manifest_aoi = None
    manifest_created_at = None
    lidar_tiles_processed = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_aoi = manifest.get("aoi")
            manifest_created_at = manifest.get("created_at")
        except json.JSONDecodeError:
            pass
    if lidar_manifest_path.exists():
        try:
            lidar_manifest = json.loads(lidar_manifest_path.read_text(encoding="utf-8"))
            lidar_tiles_processed = lidar_manifest.get("tiles_processed")
        except json.JSONDecodeError:
            pass
    lidar_tiles_downloaded = len(list((app_settings.data_dir / "raw" / "lidar" / "laz").glob("*.laz")))

    return DataStatusResponse(
        data_dir=str(app_settings.data_dir),
        manifest_exists=manifest_path.exists(),
        graph_exists=graph_path is not None,
        dem_exists=dem_path is not None,
        utci_raster=str(utci_raster) if utci_raster else None,
        shadow_raster=str(shadow_raster) if shadow_raster else None,
        graph_path=str(graph_path) if graph_path else None,
        dem_path=str(dem_path) if dem_path else None,
        manifest_aoi=manifest_aoi,
        manifest_created_at=manifest_created_at,
        canopy_raster_count=len(canopy_rasters),
        landcover_raster_count=len(landcover_rasters),
        lidar_tiles_downloaded=lidar_tiles_downloaded,
        lidar_tiles_processed=lidar_tiles_processed,
        traffic_exists=traffic_path.exists(),
        direct_shadow_ready=shadow_raster is not None,
        strict_real_ready=not missing,
        missing_required_layers=missing,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI app with injectable settings for tests."""

    app_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app_settings.preload_local_graph:
            preload_thread = threading.Thread(
                target=_preload_local_graph,
                args=(app, app_settings),
                name="routing-data-preload",
                daemon=True,
            )
            preload_thread.start()
            app.state.preload_thread = preload_thread
        yield

    app = FastAPI(
        title="Query-Conditioned Radiative-Perceptual Routing Backend",
        version="0.1.0",
        description=(
            "Computes walking or cycling route candidates optimized for "
            "micro-climate comfort, shade, scenicness, quietness and slope."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.cors_origins),
        allow_credentials="*" not in app_settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = app_settings
    app.state.edge_feature_cache = {}
    app.state.graph_cache_lock = threading.RLock()

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Return service health for load balancers and smoke tests."""

        return {"status": "ok"}

    @app.get("/data/status", response_model=DataStatusResponse)
    async def data_status() -> DataStatusResponse:
        """Report which local real-data bundle assets are available."""

        return build_data_status(app_settings)

    @app.post("/route", response_model=RouteResponse)
    async def route(request: RouteRequest) -> RouteResponse:
        """Return route candidates matching the requested comfort priorities."""

        departure_time = request.departure_time or datetime.now()
        preference = _preference_from_request(request)
        city = request.city or app_settings.default_city
        network_type = "bike" if request.mode in {"bike", "cycle", "cycling"} else app_settings.default_network_type
        dem_path = default_dem_path(app_settings.data_dir)
        snap_tolerance_m = max(
            app_settings.max_snap_distance_m,
            request.snap_tolerance_m or app_settings.max_snap_distance_m,
        )
        if dem_path is None:
            raise HTTPException(status_code=503, detail="Missing required LiDAR-derived DEM raster.")

        real_paths = None
        utci_raster = None
        if app_settings.prefer_local_data:
            try:
                real_paths = discover_real_feature_paths(app_settings.data_dir, departure_time)
                utci_raster = real_paths.utci_raster
            except RealDataMissingError as exc:
                if not app_settings.allow_synthetic_microclimate:
                    raise HTTPException(status_code=503, detail=str(exc)) from exc

        graph_path = (
            _local_graph_path(app_settings, request.mode)
            if app_settings.prefer_local_data and _looks_like_dc_request(request.origin, request.destination, city)
            else None
        )
        if graph_path:
            full_graph = _load_cached_elevated_graph(app, graph_path, dem_path)
            origin_node, destination_node, origin_snap_distance_m, destination_snap_distance_m = _nearest_route_nodes(
                full_graph,
                request.origin,
                request.destination,
            )
            if max(origin_snap_distance_m, destination_snap_distance_m) > snap_tolerance_m:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "One or both locations are outside the supported street-network coverage. "
                        f"Maximum snap distance for this request is {snap_tolerance_m:.0f} m."
                    ),
                )
            if origin_node == destination_node:
                raise HTTPException(
                    status_code=422,
                    detail="Origin and destination resolve to the same street-network node.",
                )
            raw_graph = clip_graph_to_route_area(
                full_graph,
                request.origin.as_tuple(),
                request.destination.as_tuple(),
                buffer_m=app_settings.route_clip_buffer_m,
            )
            if origin_node not in raw_graph or destination_node not in raw_graph:
                raw_graph = full_graph
        elif city:
            raw_graph = download_osm_graph(
                city,
                network_type=network_type,
                allow_synthetic_fallback=app_settings.allow_synthetic_graph,
            )
        elif app_settings.allow_synthetic_graph:
            midpoint = (
                (request.origin.lat + request.destination.lat) / 2.0,
                (request.origin.lon + request.destination.lon) / 2.0,
            )
            raw_graph = build_synthetic_graph(center=midpoint)
        else:
            raise HTTPException(
                status_code=503,
                detail="No real local graph is available for this request and no OSMnx city was provided.",
            )
        if not graph_path:
            raw_graph = apply_node_elevations_from_dem(raw_graph, dem_path)
            origin_node, destination_node, origin_snap_distance_m, destination_snap_distance_m = _nearest_route_nodes(
                raw_graph,
                request.origin,
                request.destination,
            )
            if max(origin_snap_distance_m, destination_snap_distance_m) > snap_tolerance_m:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "One or both locations are outside the supported street-network coverage. "
                        f"Maximum snap distance for this request is {snap_tolerance_m:.0f} m."
                    ),
                )
            if origin_node == destination_node:
                raise HTTPException(
                    status_code=422,
                    detail="Origin and destination resolve to the same street-network node.",
                )

        real_context = None
        use_synthetic_microclimate = (
            app_settings.allow_synthetic_microclimate
            and str(raw_graph.graph.get("source", "")).lower() == "synthetic"
        )
        if use_synthetic_microclimate:
            utci_raster = None
        elif real_paths is not None:
            real_context = RealFeatureContext(real_paths)
        elif app_settings.allow_synthetic_microclimate and app_settings.prefer_local_data:
            utci_raster = find_time_raster(app_settings.data_dir, "utci", departure_time)

        if utci_raster is None and not app_settings.allow_synthetic_microclimate:
            raise HTTPException(
                status_code=503,
                detail=(
                    "No real UTCI raster is available for this departure time. "
                    "Generate SOLWEIG outputs under data/processed/solweig_outputs "
                    "or enable ROUTING_ALLOW_SYNTHETIC_MICROCLIMATE."
                ),
            )
        try:
            if _is_shortest_request(request):
                feature_graph = raw_graph.copy()
                candidates = [
                    length_shortest_route_candidate(
                        feature_graph,
                        origin_node,
                        destination_node,
                        preference=preference,
                        departure_time=departure_time,
                        mode=request.mode,
                        sample_spacing_m=app_settings.edge_sample_spacing_m,
                        comfort_threshold=preference.comfort_threshold,
                        utci_raster_path=utci_raster,
                        real_feature_context=real_context,
                    )
                ]
            else:
                baseline_distance_m = baseline_shortest_path_distance(raw_graph, origin_node, destination_node)
                corridor_graph = clip_graph_to_detour_corridor(
                    raw_graph,
                    origin_node,
                    destination_node,
                    maximum_distance_m=baseline_distance_m * (1.0 + request.detour_ratio),
                    margin_m=app_settings.detour_corridor_margin_m,
                )
                corridor_graph = clip_graph_to_candidate_paths(
                    corridor_graph,
                    origin_node,
                    destination_node,
                    maximum_distance_m=baseline_distance_m * (1.0 + request.detour_ratio),
                    # Search breadth must not depend on the response limit;
                    # otherwise max_candidates=1 can return a worse primary route.
                    max_paths=app_settings.route_candidate_path_limit,
                )
                feature_graph = build_feature_graph(
                    corridor_graph,
                    departure_time=departure_time,
                    mode=request.mode,
                    sample_spacing_m=app_settings.edge_sample_spacing_m,
                    comfort_threshold=preference.comfort_threshold,
                    utci_raster_path=utci_raster,
                    real_feature_context=real_context,
                    feature_cache=getattr(app.state, "edge_feature_cache", None),
                )
                candidates = resource_constrained_routes(
                    feature_graph,
                    origin_node=origin_node,
                    destination_node=destination_node,
                    preference=preference,
                    delta=request.detour_ratio,
                    max_candidates=request.max_candidates,
                    max_labels_per_node=app_settings.route_search_labels_per_node,
                    max_search_seconds=app_settings.route_search_seconds,
                    max_expansions=app_settings.route_search_expansions,
                    departure_time=departure_time,
                    utci_raster_path=utci_raster,
                    maximum_distance_m=baseline_distance_m * (1.0 + request.detour_ratio),
                )
                baseline_candidate = length_shortest_route_candidate(
                    feature_graph,
                    origin_node,
                    destination_node,
                    preference=preference,
                    departure_time=departure_time,
                    mode=request.mode,
                    sample_spacing_m=app_settings.edge_sample_spacing_m,
                    comfort_threshold=preference.comfort_threshold,
                    utci_raster_path=utci_raster,
                )
                path_candidates: list[RouteCandidate] = []
                for path_nodes in feature_graph.graph.get("candidate_node_paths", []):
                    try:
                        path_candidates.append(
                            node_path_candidate(
                                feature_graph,
                                path_nodes,
                                preference,
                                departure_time=departure_time,
                                utci_raster_path=utci_raster,
                            )
                        )
                    except (KeyError, ValueError):
                        # Strict UTCI coverage can remove an edge from a stored path.
                        continue
                # Auxiliary candidates must satisfy the same original-graph
                # ceiling as the constrained solver, including parallel edges.
                maximum_distance = baseline_distance_m * (1.0 + request.detour_ratio)
                unique_candidates = {}
                for candidate in [*candidates, *path_candidates, baseline_candidate]:
                    if candidate.distance_m <= maximum_distance + 1e-9:
                        unique_candidates.setdefault(tuple(candidate.edge_ids), candidate)
                ranked = _rank_single_priority_candidates(request, list(unique_candidates.values()))
                if ranked is None:
                    ranked = sorted(unique_candidates.values(), key=lambda candidate: (candidate.cost, candidate.distance_m))
                candidates = ranked[: request.max_candidates]
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            if real_context is not None:
                real_context.close()

        selected_utci_time = raster_timestamp(utci_raster)
        uses_nearest_time = bool(
            selected_utci_time
            and (
                selected_utci_time.date() != departure_time.date()
                or selected_utci_time.hour != departure_time.hour
            )
        )
        warnings = _snap_warnings(
            origin_snap_distance_m=origin_snap_distance_m,
            destination_snap_distance_m=destination_snap_distance_m,
            threshold_m=app_settings.snap_warning_threshold_m,
        )
        if (
            request.mode in {"bike", "cycle", "cycling"}
            and graph_path is not None
            and graph_path.name != "dc_bike_graph.graphml"
        ):
            warnings.append(
                "Cycling fallback: no local DC bicycle graph is installed; this route uses the walking graph."
            )
        search_truncated = bool(feature_graph.graph.get("route_search_truncated", False))
        if search_truncated:
            warnings.append("Alternative-route search reached its performance budget; returning the best routes found.")
        if uses_nearest_time and selected_utci_time is not None:
            warnings.append(
                "Climate data fallback: using the nearest available UTCI snapshot "
                f"({selected_utci_time.isoformat(timespec='minutes')})."
            )

        return RouteResponse(
            graph_source=str(feature_graph.graph.get("source", "unknown")),
            origin_node=str(origin_node),
            destination_node=str(destination_node),
            origin_snap_distance_m=origin_snap_distance_m,
            destination_snap_distance_m=destination_snap_distance_m,
            removed_no_utci_edges=int(feature_graph.graph.get("removed_no_utci_edges", 0)),
            utci_source=str(utci_raster) if utci_raster else None,
            utci_time=selected_utci_time,
            requested_departure_time=departure_time,
            uses_nearest_time=uses_nearest_time,
            search_truncated=search_truncated,
            warnings=warnings,
            candidates=[_candidate_to_response(candidate) for candidate in candidates],
        )

    @app.get("/utci", response_model=UtciTileResponse)
    async def utci(
        lat: float = Query(38.8816, ge=-90, le=90, description="Center latitude."),
        lon: float = Query(-77.0910, ge=-180, le=180, description="Center longitude."),
        time: datetime | None = Query(None, description="Inspection timestamp."),
        cells: int = Query(5, ge=1, le=21, description="Number of cells per tile side."),
        step_degrees: float = Query(0.00025, gt=0, le=0.01, description="Grid step in degrees."),
    ) -> UtciTileResponse:
        """Return a small real UTCI tile for debugging and visualization."""

        utci_raster = find_time_raster(app_settings.data_dir, "utci", time or datetime.now())
        if utci_raster is None:
            raise HTTPException(
                status_code=503,
                detail="No real UTCI raster is available in data/processed/solweig_outputs.",
            )

        offset = (cells - 1) / 2.0
        values: list[dict[str, float]] = []
        for row in range(cells):
            for col in range(cells):
                sample_lat = lat + (row - offset) * step_degrees
                sample_lon = lon + (col - offset) * step_degrees
                samples = sample_raster_values(utci_raster, [(sample_lat, sample_lon)])
                if samples:
                    values.append({"lat": sample_lat, "lon": sample_lon, "utci": samples[0]})
        if not values:
            raise HTTPException(status_code=422, detail="The requested tile has no valid UTCI raster samples.")
        utci_values = [value["utci"] for value in values]
        return UtciTileResponse(
            center=CoordinateModel(lat=lat, lon=lon),
            time=raster_timestamp(utci_raster),
            requested_time=time,
            utci_source=str(utci_raster),
            values=values,
            min_utci=min(utci_values),
            mean_utci=sum(utci_values) / len(utci_values),
            max_utci=max(utci_values),
        )

    return app


app = create_app()
