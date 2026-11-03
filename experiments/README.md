# Experiments

The paper uses the original 500 OD pairs, five methods, four distance
allowances, and the frozen June 19 thermal fields. The primary run samples at
5 m. Every recorded 20 m path is rescored at 5 m for the sampling comparison.

The current workflow uses `configs/dc_snapshot_review3466.yaml`. Its default
spacing is the 20 m reference; pass `--sample-spacing 5` for the primary run,
as shown below. The older pilot configurations and plotting wrappers have
been removed. Frozen records and executed-source archives remain available
for auditing the experiments.

## Rebuild the results

These commands use the small frozen records and map inputs:

```bash
python experiments/analyze_sampling_validation.py
python experiments/make_corrected_figures.py --raw paper_assets/review3466/sampling5/raw --output paper_assets/review3466/sampling5/analysis
python experiments/validate_solver_oracle.py
```

`write_paper_results.py` writes the manuscript's numerical macros and tables.
Its input hashes and pinned artifact commit are in `results_generation.json`.

## Rerun routing

Fetch the seven source files through Git LFS (about 3.2 GB), then derive
above-ground building height:

```bash
git lfs pull --include="data/processed/streets/dc_walk_graph.graphml,data/processed/solweig_outputs/*2026-06-19_14.tif,data/processed/rasters/dem_1m.tif,data/processed/rasters/canopy_height_1m.tif,data/processed/rasters/landcover_1m_center_tile.tif,data/processed/solweig_inputs/building_dsm_1m.tif" --exclude=""
python scripts/derive_building_height.py --dsm data/processed/solweig_inputs/building_dsm_1m.tif --dem data/processed/rasters/dem_1m.tif --output data/processed/rasters/building_height_1m.tif
python experiments/run_corrected_validation.py preflight --sample-spacing 5 --output results/sampling-validation/preflight
```

The height script refuses to overwrite an existing product. Preflight checks
all 500 original shortest distances and hashes the inputs.

Run main shards 0–31 and sensitivity shards 0–7, changing the shard number and
output suffix together:

```bash
python experiments/run_corrected_validation.py routes --sample-spacing 5 --shards 32 --shard 0 --run-id sampling5-0 --output results/sampling-validation/routes-0
python experiments/rescore_recorded_paths.py --reference paper_assets/review3466/corrected/raw/routes_summary.csv.gz --sample-spacing 5 --shards 32 --shard 0 --output results/sampling-validation/rescore-0
python experiments/run_validation_sensitivity.py --base-spacing 5 --subset-size 100 --shards 8 --shard 0 --output results/sampling-validation/sensitivity-0
```

On Slurm, `scripts/run_sampling_validation.slurm` runs the main and rescoring
shards. Create `results/sampling-validation/logs` before submitting it and set
`ROUTING_PYTHON` to the intended environment. The recorded jobs used one CPU
and 8 GB per shard. The 1.5 s search cap can make paths vary by host; runtime
measurements include caches and are descriptive.

After all main, rescoring, and sensitivity shards finish:

```bash
python experiments/export_sampling_validation.py
python experiments/analyze_sampling_validation.py
```

The primary records are under `paper_assets/review3466/sampling5/`. The
20 m corrected run and earlier execution archive remain separate. Frozen
inputs support rerouting; incomplete original model provenance prevents exact
regeneration of the thermal field.

## Exported metadata

The export scripts make repository-local execution paths relative before
computing distribution checksums. Run identifiers, configuration identifiers,
input hashes, and routing records remain those of the recorded experiments.
The executed-source archives preserve the code used for each run.

## Rebuild thermal fields on Hopper

The SOLWEIG Slurm scripts load Hopper's compiler and GDAL modules. Submit from
the repository root, or set `ROUTING_REPO_DIR`. Set `ROUTING_VENV` to reactivate
your Python environment inside the job, or set `ROUTING_PYTHON` to its Python
executable. Temporary files use `TMPDIR` or the job's `SLURM_TMPDIR`; the pip
cache respects `PIP_CACHE_DIR` and `XDG_CACHE_HOME`.

With the intended environment activated, the paper's dated snapshot can be
requested with:

```bash
ROUTING_VENV="$VIRTUAL_ENV" sbatch --export=ALL,SOLWEIG_DATE=2026-06-19,SOLWEIG_HOUR=14 scripts/run_solweig_one_hour.slurm
```

The A100 alternative is `scripts/run_solweig_one_hour_a100.slurm`. These scripts
run the model; they do not recover the missing historical model provenance.
