# Setup

Install from the repository root in a Python 3.10+ virtual environment:

```bash
python -m pip install -e ".[dev,experiments]"
```

Optional extras are `geo` for OSM downloads and `solweig` for environmental
modeling. SOLWEIG also needs a working GDAL installation; the package alone
does not supply the system libraries.

## Data

The study config is `configs/dc_snapshot_500pair_main_methods.yaml`. It lists
the walking GraphML, UTCI, shadow, DEM, canopy, building, land-cover, and traffic
inputs. Restore the matching LFS objects before running experiments.

To prepare a new DC dataset:

```bash
python scripts/build_dc_data_bundle.py
python scripts/build_lidar_products.py
python scripts/build_weather_forcing.py --start-date 2026-06-19 --end-date 2026-06-19
```

The LiDAR downloader uses `--download-all-laz` to fetch the full point-cloud
catalog. These downloads and environmental runs can be large. The included
`run_solweig_one_hour*.slurm` scripts are Hopper launchers; check their date,
hour, and resource settings before submitting. New downloads do not recreate
the historical frozen inputs automatically.

## API and demo

```bash
uvicorn routing_backend.api:app --reload
```

Open `http://127.0.0.1:8000/docs` for requests and `/data/status` for input
availability. Missing real inputs cause an error; synthetic graph and climate
fallbacks require explicit development settings.

From `ClearHelp/frontend`, `npx expo start` launches the demo. Its routing
launcher uses port 8010 and prefers the repository virtual environment.
Set `EXPO_ROUTING_BACKEND_AUTOSTART=0` to disable that launcher.

API settings live in `src/routing_backend/api.py`. The research config
controls sampling and search independently of the API defaults.

## Research commands

Use the archived OD CSV when comparing with the paper. Generating a new sample
changes the experiment. Keep corrected-run outputs separate from historical
reanalysis; commands are in [the revision notes](../paper/REVIEW_3466.md).
