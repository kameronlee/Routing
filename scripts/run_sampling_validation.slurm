#!/bin/bash
#SBATCH --partition=normal
#SBATCH --job-name=routing-5m
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=01:30:00
#SBATCH --array=0-31
#SBATCH --output=results/sampling-validation/logs/%A_%a.out
#SBATCH --error=results/sampling-validation/logs/%A_%a.err

set -euo pipefail
cd "${ROUTING_REPO_DIR:-$SLURM_SUBMIT_DIR}"
PYTHON="${ROUTING_PYTHON:-python}"
SHARDS="${ROUTING_SHARDS:-32}"
OUTPUT="${ROUTING_OUTPUT:-results/sampling-validation}"
export PYTHONPATH="$PWD/src:$PWD${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
export GDAL_CACHEMAX=512
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

"$PYTHON" experiments/run_corrected_validation.py routes \
    --sample-spacing 5 --shards "$SHARDS" --shard "$SLURM_ARRAY_TASK_ID" \
    --run-id "sampling5-${SLURM_ARRAY_JOB_ID}-${SLURM_ARRAY_TASK_ID}" \
    --output "$OUTPUT/routes-$SLURM_ARRAY_TASK_ID"
"$PYTHON" experiments/rescore_recorded_paths.py \
    --reference paper_assets/review3466/corrected/raw/routes_summary.csv.gz \
    --sample-spacing 5 --shards "$SHARDS" --shard "$SLURM_ARRAY_TASK_ID" \
    --output "$OUTPUT/rescore-$SLURM_ARRAY_TASK_ID"
