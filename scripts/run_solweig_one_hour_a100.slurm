#!/bin/bash
#SBATCH --partition=gpuq
#SBATCH --qos=gpu
#SBATCH --job-name=solweig-one-hour-a100
#SBATCH --output=/scratch/%u/%x-%j.out
#SBATCH --error=/scratch/%u/%x-%j.err
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --gres=gpu:A100.80gb:1
#SBATCH --mem=122G
#SBATCH --time=0-08:00:00
#SBATCH --export=ALL

set -euo pipefail
umask 0027

REPO_DIR="${ROUTING_REPO_DIR:-${SLURM_SUBMIT_DIR:-/scratch/klee206/work/Routing}}"
cd "$REPO_DIR"

SOLWEIG_TIMEZONE="${SOLWEIG_TIMEZONE:-America/New_York}"
SOLWEIG_DATE="${SOLWEIG_DATE:-$(TZ="$SOLWEIG_TIMEZONE" date +%F)}"
SOLWEIG_HOUR="${SOLWEIG_HOUR:-14}"
SOLWEIG_TILE_SIZE="${SOLWEIG_TILE_SIZE:-1000}"
SOLWEIG_WORK_DIR="${SOLWEIG_WORK_DIR:-data/processed/solweig_gpu_work}"
SOLWEIG_FILL_UTCI_NANS="${SOLWEIG_FILL_UTCI_NANS:-1}"
SOLWEIG_UTCI_FILL_DISTANCE="${SOLWEIG_UTCI_FILL_DISTANCE:-256}"
SOLWEIG_SAVE_SHADOW="${SOLWEIG_SAVE_SHADOW:-1}"
SOLWEIG_MET_FILE_CUSTOM="${SOLWEIG_MET_FILE:+1}"
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

echo "Running one-hour SOLWEIG-GPU production job on A100"
echo "repo: $PWD"
echo "timezone: $SOLWEIG_TIMEZONE"
echo "date: $SOLWEIG_DATE"
echo "hour: $SOLWEIG_HOUR"
echo "met file: $SOLWEIG_MET_FILE"
echo "work dir: $SOLWEIG_WORK_DIR"
echo "tile size: $SOLWEIG_TILE_SIZE"
echo "save shadow: $SOLWEIG_SAVE_SHADOW"

if [[ ! -f "$SOLWEIG_MET_FILE" ]]; then
  if [[ -n "$SOLWEIG_MET_FILE_CUSTOM" ]]; then
    echo "Requested SOLWEIG_MET_FILE does not exist: $SOLWEIG_MET_FILE" >&2
    exit 1
  fi
  echo "Met file not found; building weather forcing for $SOLWEIG_DATE"
  python scripts/build_weather_forcing.py \
    --start-date "$SOLWEIG_DATE" \
    --end-date "$SOLWEIG_DATE"
fi

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

SOLWEIG_RUN_ARGS=(
  scripts/run_solweig_gpu.py
  --date "$SOLWEIG_DATE" \
  --met-file "$SOLWEIG_MET_FILE" \
  --hour "$SOLWEIG_HOUR" \
  --work-dir "$SOLWEIG_WORK_DIR" \
  --tile-size "$SOLWEIG_TILE_SIZE" \
  --publish
)
if [[ "$SOLWEIG_SAVE_SHADOW" != "0" ]]; then
  SOLWEIG_RUN_ARGS+=(--save-shadow)
fi

python "${SOLWEIG_RUN_ARGS[@]}"

if [[ "$SOLWEIG_FILL_UTCI_NANS" != "0" ]]; then
  SOLWEIG_HOUR_PADDED="$(printf "%02d" "$SOLWEIG_HOUR")"
  PUBLISHED_UTCI="data/processed/solweig_outputs/utci_${SOLWEIG_DATE}_${SOLWEIG_HOUR_PADDED}.tif"
  if [[ -f "$PUBLISHED_UTCI" ]]; then
    python scripts/fill_utci_nans.py \
      "$PUBLISHED_UTCI" \
      --in-place \
      --max-search-distance "$SOLWEIG_UTCI_FILL_DISTANCE"
  else
    echo "Expected published UTCI raster not found for NaN fill: $PUBLISHED_UTCI" >&2
    exit 1
  fi
fi

echo "Published SOLWEIG outputs:"
ls -lh data/processed/solweig_outputs || true

python - <<'PY'
from routing_backend.api import build_data_status

print(build_data_status().model_dump())
PY
