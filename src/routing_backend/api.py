"""FastAPI application for radiative-perceptual routing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from routing_backend.data_ingestion import (
    apply_node_elevations_from_dem,
    build_synthetic_graph,
    clip_graph_to_route_area,
    download_osm_graph,
    load_street_graph,
    nearest_node,
)
from routing_backend.microclimate_model import Coordinate
from routing_backend.preferences import Preference, preference_from_descriptors
from routing_backend.raster_data import default_data_dir, default_dem_path, find_time_raster, sample_raster_values
from routing_backend.real_features import RealDataMissingError, RealFeatureContext, discover_real_feature_paths
from routing_backend.route_engine import (
    RouteCandidate,
    build_feature_graph,
    resource_constrained_routes,
)


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    default_city: str | None = None
    default_network_type: str = "walk"
    data_dir: Path = default_data_dir()
    prefer_local_data: bool = True
    route_clip_buffer_m: float = 1_500.0
    allow_synthetic_graph: bool = False
    allow_synthetic_microclimate: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from environment variables."""

        return cls(
            default_city=os.getenv("ROUTING_DEFAULT_CITY"),
            default_network_type=os.getenv("ROUTING_NETWORK_TYPE", "walk"),
            data_dir=Path(os.getenv("ROUTING_DATA_DIR", str(default_data_dir()))),
            prefer_local_data=os.getenv("ROUTING_PREFER_LOCAL_DATA", "1") != "0",
            route_clip_buffer_m=float(os.getenv("ROUTING_ROUTE_CLIP_BUFFER_M", "1500")),
            allow_synthetic_graph=os.getenv("ROUTING_ALLOW_SYNTHETIC_GRAPH", "0") == "1",
            allow_synthetic_microclimate=os.getenv("ROUTING_ALLOW_SYNTHETIC_MICROCLIMATE", "0") == "1",
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


class RouteResponse(BaseModel):
    """Route search response with selected graph metadata."""

    graph_source: str
    origin_node: str
    destination_node: str
    candidates: list[RouteCandidateResponse]


class UtciTileResponse(BaseModel):
    """Small real UTCI tile sampled from the selected SOLWEIG GeoTIFF."""

    center: CoordinateModel
    time: datetime | None
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
    graph_path: str | None
    dem_path: str | None
    manifest_aoi: str | None = None
    manifest_created_at: str | None = None
    canopy_raster_count: int = 0
    landcover_raster_count: int = 0
    lidar_tiles_downloaded: int = 0
    lidar_tiles_processed: int | None = None
    traffic_exists: bool = False
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
    if city and "washington" not in city.lower() and "district of columbia" not in city.lower():
        return False
    for coordinate in (origin, destination):
        if not (38.75 <= coordinate.lat <= 39.05 and -77.20 <= coordinate.lon <= -76.85):
            return False
    return True


def _load_cached_graph(app: FastAPI, graph_path: Path):
    cache = getattr(app.state, "graph_cache", {})
    key = str(graph_path)
    if key not in cache:
        cache[key] = load_street_graph(graph_path)
        app.state.graph_cache = cache
    return cache[key]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI app with injectable settings for tests."""

    app_settings = settings or Settings.from_env()
    app = FastAPI(
        title="Query-Conditioned Radiative-Perceptual Routing Backend",
        version="0.1.0",
        description=(
            "Computes walking or cycling route candidates optimized for "
            "micro-climate comfort, shade, scenicness, quietness and slope."
        ),
    )
    app.state.settings = app_settings

    @app.get("/health")
    def health() -> dict[str, str]:
        """Return service health for load balancers and smoke tests."""

        return {"status": "ok"}

    @app.get("/data/status", response_model=DataStatusResponse)
    def data_status() -> DataStatusResponse:
        """Report which local real-data bundle assets are available."""

        graph_path = _local_graph_path(app_settings, "walk")
        dem_path = default_dem_path(app_settings.data_dir)
        utci_raster = find_time_raster(app_settings.data_dir, "utci", datetime.now())
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
            graph_path=str(graph_path) if graph_path else None,
            dem_path=str(dem_path) if dem_path else None,
            manifest_aoi=manifest_aoi,
            manifest_created_at=manifest_created_at,
            canopy_raster_count=len(canopy_rasters),
            landcover_raster_count=len(landcover_rasters),
            lidar_tiles_downloaded=lidar_tiles_downloaded,
            lidar_tiles_processed=lidar_tiles_processed,
            traffic_exists=traffic_path.exists(),
            strict_real_ready=not missing,
            missing_required_layers=missing,
        )

    @app.post("/route", response_model=RouteResponse)
    def route(request: RouteRequest) -> RouteResponse:
        """Return route candidates matching the requested comfort priorities."""

        departure_time = request.departure_time or datetime.now()
        preference = _preference_from_request(request)
        city = request.city or app_settings.default_city
        network_type = "bike" if request.mode in {"bike", "cycle", "cycling"} else app_settings.default_network_type
        real_paths = None
        utci_raster = None
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
            raw_graph = _load_cached_graph(app, graph_path)
            raw_graph = clip_graph_to_route_area(
                raw_graph,
                request.origin.as_tuple(),
                request.destination.as_tuple(),
                buffer_m=app_settings.route_clip_buffer_m,
            )
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

        dem_path = default_dem_path(app_settings.data_dir)
        if dem_path is None:
            raise HTTPException(status_code=503, detail="Missing required LiDAR-derived DEM raster.")
        raw_graph = apply_node_elevations_from_dem(raw_graph, dem_path)
        real_context = None
        if real_paths is not None:
            real_context = RealFeatureContext(real_paths)
        elif app_settings.allow_synthetic_microclimate:
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
            feature_graph = build_feature_graph(
                raw_graph,
                departure_time=departure_time,
                mode=request.mode,
                comfort_threshold=preference.comfort_threshold,
                utci_raster_path=utci_raster,
                real_feature_context=real_context,
            )
            origin_node = nearest_node(feature_graph, request.origin.as_tuple())
            destination_node = nearest_node(feature_graph, request.destination.as_tuple())
            candidates = resource_constrained_routes(
                feature_graph,
                origin_node=origin_node,
                destination_node=destination_node,
                preference=preference,
                delta=request.detour_ratio,
                max_candidates=request.max_candidates,
                departure_time=departure_time,
                utci_raster_path=utci_raster,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            if real_context is not None:
                real_context.close()

        return RouteResponse(
            graph_source=str(feature_graph.graph.get("source", "unknown")),
            origin_node=str(origin_node),
            destination_node=str(destination_node),
            candidates=[_candidate_to_response(candidate) for candidate in candidates],
        )

    @app.get("/utci", response_model=UtciTileResponse)
    def utci(
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
            time=time,
            values=values,
            min_utci=min(utci_values),
            mean_utci=sum(utci_values) / len(utci_values),
            max_utci=max(utci_values),
        )

    return app


app = create_app()
