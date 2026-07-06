#!/usr/bin/env python
"""Run route benchmarks over OD pairs, methods and detour ratios."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routing_backend.benchmark_runner import run_route_benchmark
from routing_backend.experiment_config import load_experiment_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--od-pairs", help="OD CSV path. Defaults to results/<study>/od_pairs.csv.")
    parser.add_argument("--methods", help="Comma-separated method list.")
    parser.add_argument("--limit", type=int, help="Debug limit on OD pair rows.")
    parser.add_argument("--parallel-workers", type=int, default=1, help="Reserved for future safe parallel execution.")
    args = parser.parse_args()

    config = load_experiment_config(args.config)
    methods = [value.strip() for value in args.methods.split(",")] if args.methods else None
    outputs = run_route_benchmark(
        config,
        od_pairs_path=args.od_pairs or config.output_dir / "od_pairs.csv",
        methods=methods,
        limit=args.limit,
    )
    for name, path in outputs.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
