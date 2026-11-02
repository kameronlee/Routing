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
REPO_DIR="${ROUTING_REPO_DIR:-${SLURM_SUBMIT_DIR:-$PWD}}"
cd "$REPO_DIR"

# Override SOLWEIG_DATE to build a different snapshot.
SOLWEIG_DATE="${SOLWEIG_DATE:-2026-05-23}"
SOLWEIG_HOUR="${SOLWEIG_HOUR:-14}"
SOLWEIG_TILE_SIZE="${SOLWEIG_TILE_SIZE:-1000}"
SOLWEIG_WORK_DIR="${SOLWEIG_WORK_DIR:-data/processed/solweig_gpu_work}"
SOLWEIG_MET_FILE="${SOLWEIG_MET_FILE:-data/processed/solweig_inputs/met_forcing_${SOLWEIG_DATE}_${SOLWEIG_DATE}.txt}"

module load hosts/hopper
module load gnu/12.3.0
module load openmpi/4.1.6-a2
module load gdal/3.8.5-7p

if [[ -n "${ROUTING_VENV:-}" ]]; then
  source "$ROUTING_VENV/bin/activate"
fi
ROUTING_PYTHON="${ROUTING_PYTHON:-python}"

export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
export TMPDIR="${TMPDIR:-${SLURM_TMPDIR:-/tmp/routing-${USER:-user}}}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/pip}"

mkdir -p "$TMPDIR" "$PIP_CACHE_DIR" "$(dirname "$SOLWEIG_WORK_DIR")"

echo "Running one-hour SOLWEIG-GPU production job"
echo "repo: $PWD"
echo "date: $SOLWEIG_DATE"
echo "hour: $SOLWEIG_HOUR"
echo "met file: $SOLWEIG_MET_FILE"
echo "work dir: $SOLWEIG_WORK_DIR"
echo "tile size: $SOLWEIG_TILE_SIZE"

nvidia-smi

"$ROUTING_PYTHON" - <<'PY'
from osgeo import gdal
import torch

print("GDAL:", gdal.VersionInfo("--version"))
print("Torch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
PY

"$ROUTING_PYTHON" scripts/run_solweig_gpu.py \
  --date "$SOLWEIG_DATE" \
  --met-file "$SOLWEIG_MET_FILE" \
  --hour "$SOLWEIG_HOUR" \
  --work-dir "$SOLWEIG_WORK_DIR" \
  --tile-size "$SOLWEIG_TILE_SIZE" \
  --publish

echo "Published SOLWEIG outputs:"
ls -lh data/processed/solweig_outputs || true
