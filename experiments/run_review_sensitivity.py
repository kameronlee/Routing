"""Run review-3466 coefficient, threshold and sampling checks on real inputs."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routing_backend.experiment_config import load_experiment_config
from routing_backend.review_sensitivity import run_review_sensitivity


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--od-pairs", required=True)
    parser.add_argument("--subset-size", type=int, default=100)
    args = parser.parse_args()
    print(run_review_sensitivity(load_experiment_config(args.config),
          od_pairs_path=args.od_pairs, subset_size=args.subset_size))
