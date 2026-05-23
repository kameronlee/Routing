# Query-Conditioned Radiative-Perceptual Routing Backend

This project is a Python backend for walking and cycling routes optimized for
micro-climate comfort, shade, scenicness, quietness and slope. The runtime is
configured for strict real-data routing: it uses local staged DC datasets and
fails loudly when a required real layer is missing.

## What Is Included

- `data_ingestion.py`: OSMnx/GraphML street graph loading and LiDAR DEM elevation sampling.
- `raster_data.py`: real GeoTIFF discovery/sampling for DEM and SOLWEIG outputs.
- `real_features.py`: joins LiDAR canopy height, optional land-cover and DDOT AADT traffic data onto route edges.
- `microclimate_model.py`: geometry densification and UTCI raster sampling.
- `perception_model.py`: slope helpers and development fallback scoring utilities.
- `preferences.py`: user preference dataclass plus descriptor-to-weight mapping.
- `route_engine.py`: edge feature extraction, scalar utility cost and resource-constrained routing.
- `api.py`: FastAPI app with `/health`, `/data/status`, `/route` and `/utci`.
- `scripts/build_dc_data_bundle.py`: Washington, D.C. public-data downloader.
- `scripts/build_lidar_products.py`: rasterizes classified NOAA COPC LAZ tiles into DSM, building DSM and tree CDSM.
- `scripts/build_weather_forcing.py`: downloads real hourly weather/solar forcing for SOLWEIG inputs.
- `tests/`: unit and integration tests, including explicit development fallback tests.

## Install

Use Python 3.10 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

For real OSM downloads, install the optional OSM stack:

```bash
python -m pip install -e ".[dev,geo]"
```

For SOLWEIG-GPU execution:

```bash
python -m pip install -e ".[solweig]"
```

On this Windows/Python 3.12 workspace, `solweig-gpu` also needed GDAL Python
bindings from a prebuilt wheel:

```bash
python -m pip install https://wheelhouse.openquake.org/v3/windows/py312/gdal-3.10.2-cp312-cp312-win_amd64.whl
```

The API no longer uses synthetic data unless you explicitly enable development
fallbacks with environment variables.

## Build The Washington, D.C. Data Bundle

The repository now includes a repeatable downloader for the DC real-data bundle:

```bash
python scripts/build_dc_data_bundle.py
```

The default run downloads/stages:

- DC administrative boundary from DCGIS.
- Geofabrik DC OSM PBF and shapefile extracts.
- OSMnx walking GraphML for DC.
- DDOT 2023 traffic volume GeoJSON.
- DC 2020 tree-canopy summary and center raster tile.
- DC 2020 generalized land-cover center raster tile.
- NOAA-hosted DC OCTO 2022 full-city 1 m DEM.
- NOAA LiDAR URL list, tile index metadata and one representative COPC LAZ tile.

The full NOAA point-cloud catalog is intentionally opt-in because it is
multi-GB:

```bash
python scripts/build_dc_data_bundle.py --download-all-laz
```

After downloading the full point-cloud catalog, generate the LiDAR-derived
SOLWEIG/routing rasters:

```bash
python scripts/build_lidar_products.py
```

This builds:

- `data/processed/solweig_inputs/dsm_1m.tif`
- `data/processed/solweig_inputs/building_dsm_1m.tif`
- `data/processed/solweig_inputs/trees_cdsm_1m.tif`
- `data/processed/rasters/canopy_height_1m.tif`

For weather forcing:

```bash
python scripts/build_weather_forcing.py --start-date 2026-05-23 --end-date 2026-05-23
```

To run SOLWEIG-GPU after the optional SOLWEIG stack is installed:

```bash
python scripts/run_solweig_gpu.py ^
  --date 2026-05-23 ^
  --met-file data\processed\solweig_inputs\met_forcing_2026-05-23_2026-05-23.txt ^
  --work-dir data\processed\solweig_gpu_work ^
  --tile-size 1000 ^
  --publish
```

For a quick real-data smoke test before a long production run:

```bash
python scripts/run_solweig_gpu.py ^
  --date 2026-05-23 ^
  --met-file data\processed\solweig_inputs\met_forcing_2026-05-23_2026-05-23.txt ^
  --work-dir data\processed\solweig_gpu_smoke ^
  --subset-size-m 128 ^
  --tile-size 128 ^
  --clean-work-dir
```

The smoke output stays under `data/processed/solweig_gpu_smoke` and is not
published to the API's strict routing UTCI directory.

The manifest is written to `data/metadata/manifest.json`.

## Run The API

```bash
uvicorn routing_backend.api:app --reload
```

On Windows, this repository also includes a file-backed launcher that works well
when the service is started from tooling without a normal console:

```bash
python scripts/run_dev_server.py
```

Open:

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/data/status`
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/utci`

Example route request:

```bash
curl -X POST http://127.0.0.1:8000/route ^
  -H "Content-Type: application/json" ^
  -d "{\"origin\":{\"lat\":38.8805,\"lon\":-77.0920},\"destination\":{\"lat\":38.8828,\"lon\":-77.0896},\"departure_time\":\"2026-07-01T14:00:00\",\"descriptors\":[\"heat sensitive\",\"noise averse\"],\"detour_ratio\":0.3}"
```

You can also request an OSMnx place when the optional stack and network are
available:

```json
{
  "origin": {"lat": 38.8895, "lon": -77.0353},
  "destination": {"lat": 38.8977, "lon": -77.0365},
  "city": "Washington, District of Columbia, USA",
  "mode": "walk",
  "descriptors": ["heat sensitive", "scenic"],
  "detour_ratio": 0.25
}
```

## Configuration

Configuration is read from environment variables:

- `ROUTING_DEFAULT_CITY`: optional OSMnx place name used when requests omit `city`.
- `ROUTING_NETWORK_TYPE`: OSMnx network type, default `walk`.
- `ROUTING_DATA_DIR`: local data bundle directory, default `./data`.
- `ROUTING_PREFER_LOCAL_DATA`: set to `0` to ignore local GraphML/rasters.
- `ROUTING_ROUTE_CLIP_BUFFER_M`: route corridor buffer around origin/destination, default `1500`.
- `ROUTING_ALLOW_SYNTHETIC_GRAPH`: development-only escape hatch; set to `1` to allow the test grid.
- `ROUTING_ALLOW_SYNTHETIC_MICROCLIMATE`: development-only escape hatch; set to `1` to allow placeholder UTCI.

No external API keys are hard-coded.

## Testing

```bash
pytest
```

Most tests use tiny in-memory fixtures, and development fallback tests are
explicitly marked through settings. Runtime defaults remain strict-real-data.

## Data Pipeline Notes

The backend requires real UTCI rasters in
`data/processed/solweig_outputs/utci_YYYY-MM-DD_HH.tif` and samples them along
edges/routes. If no UTCI raster exists, `/route` and `/utci` return a 503 with
the missing layer instead of fabricating heat values.

Current all-real routing requirements:

- `data/processed/streets/dc_walk_graph.graphml`
- `data/processed/rasters/dem_1m.tif`
- `data/processed/rasters/canopy_height_1m.tif` or another real tree-canopy raster
- `data/raw/traffic_noise/ddot_traffic_volume_2023.geojson`
- `data/processed/solweig_outputs/utci_YYYY-MM-DD_HH.tif`

`GET /data/status` reports whether these are available. At the moment, the DC
bundle is blocked only on real SOLWEIG/SOLWEIG-GPU UTCI output rasters.
The SOLWEIG-GPU runner has been validated on a real clipped LiDAR subset; full
1 m DC production runs are compute-heavy on CPU-only machines.

Scenic and quiet scores now join real route-edge samples from LiDAR canopy
height, optional land-cover rasters and DDOT AADT traffic lines. Missing
LiDAR/canopy or traffic coverage raises an API error in strict mode.

The routing algorithm first computes the shortest-path distance `d*`, then runs
a label-setting constrained search to minimize weighted radiative-perceptual
cost while enforcing:

```text
route_distance <= (1 + detour_ratio) * d*
```
