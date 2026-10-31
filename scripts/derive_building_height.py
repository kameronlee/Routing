#!/usr/bin/env python
"""Convert aligned building DSM and terrain elevation to height above ground."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def derive_height(dsm_path, dem_path, output_path):
    output_path = Path(output_path)
    if output_path.resolve() in (Path(dsm_path).resolve(), Path(dem_path).resolve()):
        raise ValueError("Output must differ from both source rasters")
    if output_path.exists():
        raise FileExistsError(output_path)
    with rasterio.open(dsm_path) as dsm, rasterio.open(dem_path) as dem:
        if (dsm.shape != dem.shape or dsm.crs != dem.crs or dsm.transform != dem.transform):
            raise ValueError("DSM and DEM must have identical grids and coordinate systems")
        profile = dem.profile.copy()
        profile.update(dtype="float32", count=1, nodata=-9999.0, tiled=True,
                       blockxsize=512, blockysize=512, compress="deflate", predictor=3, BIGTIFF="IF_SAFER")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        valid_count = occupied_count = 0
        maximum = 0.0
        with rasterio.open(output_path, "w", **profile) as target:
            for _, window in target.block_windows(1):
                surface = dsm.read(1, window=window, masked=True)
                ground = dem.read(1, window=window, masked=True)
                valid = (~np.ma.getmaskarray(surface) & ~np.ma.getmaskarray(ground)
                         & np.isfinite(surface.data) & np.isfinite(ground.data))
                height = np.full(surface.shape, -9999.0, dtype="float32")
                height[valid] = np.maximum(0.0, surface.data[valid] - ground.data[valid])
                valid_count += int(valid.sum())
                occupied_count += int(np.sum(height[valid] >= 2.0))
                if valid.any():
                    maximum = max(maximum, float(height[valid].max()))
                target.write(height, 1, window=window)
            target.update_tags(quantity="building height above ground", units="m",
                               derivation="max(0, building_DSM - DEM); source NoData retained")
    manifest = {"formula": "max(0, building_DSM - DEM)", "units": "m", "grid_resampling": False,
                "source_dsm_sha256": sha256(dsm_path), "source_dem_sha256": sha256(dem_path),
                "output_sha256": sha256(output_path), "valid_cells": valid_count,
                "cells_at_least_2m": occupied_count, "max_height_m": maximum,
                "script_sha256": sha256(__file__)}
    output_path.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsm", type=Path, required=True)
    parser.add_argument("--dem", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(derive_height(args.dsm, args.dem, args.output), indent=2))
