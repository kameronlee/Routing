# Experiments

The revised paper uses `configs/dc_snapshot_review3466.yaml` and the original
`paper_assets/review3466/raw/od_pairs.csv`. Frozen results are under
`paper_assets/review3466/corrected/`; reanalysis needs no large raster download.

```bash
python experiments/analyze_corrected_validation.py
python experiments/make_corrected_figures.py
python experiments/validate_solver_oracle.py
```

## Rerun routing

Install Git LFS and fetch only the seven source inputs (about 3.2 GB):

```bash
git lfs pull --include="data/processed/streets/dc_walk_graph.graphml,data/processed/solweig_outputs/*2026-06-19_14.tif,data/processed/rasters/dem_1m.tif,data/processed/rasters/canopy_height_1m.tif,data/processed/rasters/landcover_1m_center_tile.tif,data/processed/solweig_inputs/building_dsm_1m.tif" --exclude=""
python scripts/derive_building_height.py --dsm data/processed/solweig_inputs/building_dsm_1m.tif --dem data/processed/rasters/dem_1m.tif --output data/processed/rasters/building_height_1m.tif
python experiments/run_corrected_validation.py preflight --output results/review3466-height-preflight
```

The height script refuses to overwrite an existing product. The preflight
checks all 500 original shortest distances and records input/source hashes.

Run main shards 0–7 and sensitivity shards 0–1, changing `--shard` and the
output suffix together:

```bash
python experiments/run_corrected_validation.py routes --shards 8 --shard 0 --output results/review3466-final-0
python experiments/run_validation_sensitivity.py --subset-size 100 --shards 2 --shard 0 --output results/review3466-final-sensitivity-0
python experiments/inspect_rasters.py --config configs/dc_snapshot_review3466.yaml --sample-count 10000 --output-dir results/review3466-raster-qc
```

After every shard finishes, freeze and analyze the outputs:

```bash
python experiments/export_validation_bundle.py
python experiments/analyze_corrected_validation.py
python experiments/make_corrected_figures.py
```

The recorded Hopper runs used two CPUs per shard and a 16 GB memory request.
The 1.5 s wall-clock cap can make rerouted paths vary by machine; the frozen
records reproduce the reported tables. Timings include shared caches and
should not be used as a controlled speed ranking.

The original run remains separate. Reanalyze it with
`python experiments/reanalyze_geohealth3466.py --figures`.
