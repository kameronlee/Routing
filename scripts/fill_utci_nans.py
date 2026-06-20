"""Fill missing UTCI raster cells from neighboring modeled UTCI values."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

import numpy as np
import rasterio
from rasterio.fill import fillnodata


def fill_utci_nans(
    source: Path,
    destination: Path,
    *,
    max_search_distance: float,
    smoothing_iterations: int,
) -> dict[str, float | int | str]:
    """Fill non-finite UTCI cells and write a repaired GeoTIFF."""

    with rasterio.open(source) as dataset:
        data = dataset.read(1, masked=False)
        profile = dataset.profile.copy()
        nodata = dataset.nodata

    valid = np.isfinite(data)
    if nodata is not None:
        valid &= data != nodata

    total_cells = int(data.size)
    missing_before = int((~valid).sum())
    if missing_before == 0:
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        return {
            "source": str(source),
            "destination": str(destination),
            "total_cells": total_cells,
            "missing_before": 0,
            "missing_after": 0,
            "missing_before_pct": 0.0,
            "missing_after_pct": 0.0,
        }
    if not valid.any():
        raise ValueError(f"No valid UTCI cells available to fill {source}")

    filled = fillnodata(
        data,
        mask=valid.astype("uint8"),
        max_search_distance=max_search_distance,
        smoothing_iterations=smoothing_iterations,
    )
    missing_after = int((~np.isfinite(filled)).sum())

    destination.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(destination, "w", **profile) as output:
        output.write(filled.astype(profile["dtype"], copy=False), 1)

    return {
        "source": str(source),
        "destination": str(destination),
        "total_cells": total_cells,
        "missing_before": missing_before,
        "missing_after": missing_after,
        "missing_before_pct": missing_before / total_cells * 100.0,
        "missing_after_pct": missing_after / total_cells * 100.0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Input UTCI GeoTIFF.")
    parser.add_argument(
        "destination",
        type=Path,
        nargs="?",
        help="Output GeoTIFF. Omit when using --in-place.",
    )
    parser.add_argument("--in-place", action="store_true", help="Replace the source file with the repaired raster.")
    parser.add_argument("--max-search-distance", type=float, default=256.0)
    parser.add_argument("--smoothing-iterations", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    if args.in_place:
        if args.destination is not None:
            raise SystemExit("Do not pass destination with --in-place")
        destination = source.with_name(f".{source.name}.fill-tmp")
    else:
        if args.destination is None:
            raise SystemExit("Pass an output path or --in-place")
        destination = args.destination.resolve()

    summary = fill_utci_nans(
        source,
        destination,
        max_search_distance=args.max_search_distance,
        smoothing_iterations=args.smoothing_iterations,
    )
    if args.in_place:
        destination.replace(source)
        summary["destination"] = str(source)

    print(
        "Filled UTCI NaNs: "
        f"{summary['missing_before']} -> {summary['missing_after']} "
        f"({summary['missing_before_pct']:.4f}% -> {summary['missing_after_pct']:.4f}%) "
        f"in {summary['destination']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
