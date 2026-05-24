#!/bin/bash
#SBATCH --partition=gpuq
#SBATCH --qos=gpu
#SBATCH --job-name=solweig-one-hour
#SBATCH --output=/scratch/%u/%x-%j.out
#SBATCH --error=/scratch/%u/%x-%j.err
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=28
#SBATCH --gres=gpu:h100.80gb:1
#SBATCH --mem=497G
#SBATCH --time=0-08:00:00
#SBATCH --export=ALL

set -euo pipefail
umask 0027

# Submit from the repository root, or set ROUTING_REPO_DIR at submission time.
REPO_DIR="${ROUTING_REPO_DIR:-${SLURM_SUBMIT_DIR:-/scratch/klee206/work/Routing}}"
cd "$REPO_DIR"

# Defaults match the one-hour production UTCI run used during validation.
SOLWEIG_DATE="${SOLWEIG_DATE:-2026-05-23}"
SOLWEIG_HOUR="${SOLWEIG_HOUR:-14}"
SOLWEIG_TILE_SIZE="${SOLWEIG_TILE_SIZE:-1000}"
SOLWEIG_WORK_DIR="${SOLWEIG_WORK_DIR:-data/processed/solweig_gpu_work}"
SOLWEIG_MET_FILE="${SOLWEIG_MET_FILE:-data/processed/solweig_inputs/met_forcing_${SOLWEIG_DATE}_${SOLWEIG_DATE}.txt}"

module load hosts/hopper
module load gnu/12.3.0
module load openmpi/4.1.6-a2
module load gdal/3.8.5-7p

source /scratch/klee206/envs/routing-venv/bin/activate

export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
export TMPDIR="${TMPDIR:-/scratch/klee206/tmp}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/scratch/klee206/pip-cache}"

mkdir -p "$TMPDIR" "$PIP_CACHE_DIR" "$(dirname "$SOLWEIG_WORK_DIR")"

echo "Running one-hour SOLWEIG-GPU production job"
echo "repo: $PWD"
echo "date: $SOLWEIG_DATE"
echo "hour: $SOLWEIG_HOUR"
echo "met file: $SOLWEIG_MET_FILE"
echo "work dir: $SOLWEIG_WORK_DIR"
echo "tile size: $SOLWEIG_TILE_SIZE"

nvidia-smi

python - <<'PY'
from osgeo import gdal
import torch

print("GDAL:", gdal.VersionInfo("--version"))
print("Torch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
PY

python scripts/run_solweig_gpu.py \
  --date "$SOLWEIG_DATE" \
  --met-file "$SOLWEIG_MET_FILE" \
  --hour "$SOLWEIG_HOUR" \
  --work-dir "$SOLWEIG_WORK_DIR" \
  --tile-size "$SOLWEIG_TILE_SIZE" \
  --publish

echo "Published SOLWEIG outputs:"
ls -lh data/processed/solweig_outputs || true

python - <<'PY'
from routing_backend.api import build_data_status

print(build_data_status().model_dump())
PY
