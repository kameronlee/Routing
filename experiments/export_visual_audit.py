#!/usr/bin/env python
"""Export remote visual audit route cases."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routing_backend.audit_exports import export_visual_audit_cases
from routing_backend.experiment_config import load_experiment_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--routes-summary")
    parser.add_argument("--routes-geojson")
    parser.add_argument("--count", type=int, default=12)
    args = parser.parse_args()

    config = load_experiment_config(args.config)
    outputs = export_visual_audit_cases(
        config,
        routes_summary_path=args.routes_summary or config.output_dir / "routes_summary.csv",
        routes_geojson_path=args.routes_geojson or config.output_dir / "routes.geojson",
        count=args.count,
    )
    for name, path in outputs.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
