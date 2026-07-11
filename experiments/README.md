# Routing Paper Experiments

This folder contains command-line entrypoints for a reproducible computational
routing study. The scripts use the backend's real GraphML, UTCI GeoTIFF, and
direct-shadow GeoTIFF inputs. They do not start the FastAPI server and do not
use frontend code.

The main DC snapshot pipeline is:

```bash
python experiments/inspect_rasters.py --config configs/dc_snapshot.yaml
python experiments/generate_od_pairs.py --config configs/dc_snapshot.yaml
python experiments/run_route_benchmark.py --config configs/dc_snapshot.yaml
python experiments/run_ablations.py --config configs/dc_snapshot.yaml
python experiments/run_sensitivity.py --config configs/dc_snapshot.yaml
python experiments/export_visual_audit.py --config configs/dc_snapshot.yaml
python experiments/aggregate_results.py --config configs/dc_snapshot.yaml
python experiments/make_figures.py --config configs/dc_snapshot.yaml
```

All random sampling accepts a fixed seed through the config or CLI. Main
experiments fail if required real rasters or graph files are missing. Synthetic
data is only appropriate for unit tests.

Outputs are written under `results/<study>/` as CSV, JSON, GeoJSON, Markdown,
and PNG files. Large generated outputs should remain uncommitted.
