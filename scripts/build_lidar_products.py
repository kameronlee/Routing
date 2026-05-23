"""Build SOLWEIG-ready DSM and vegetation rasters from NOAA DC COPC LAZ tiles.

The script aligns outputs to the NOAA DC OCTO 2022 1 m DEM grid. It can process
the currently downloaded sample tile, or the full catalog after running:

    python scripts/build_dc_data_bundle.py --download-all-laz

Outputs:

- data/processed/solweig_inputs/dsm_1m.tif
- data/processed/solweig_inputs/building_dsm_1m.tif
- data/processed/solweig_inputs/trees_cdsm_1m.tif
- data/processed/rasters/canopy_height_1m.tif
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Iterable

import laspy
import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.windows import Window

BUILDING_CLASS = 6
VEGETATION_CLASSES = {3, 4, 5}
EXCLUDED_SURFACE_CLASSES = {7, 18}
NODATA = -9999.0


@dataclass(frozen=True)
class TileResult:
    """Processing metadata for one LAZ tile."""

    path: str
    chunks: int
    points_seen: int
    points_used: int
    building_points: int
    vegetation_points: int


def laz_files(root: Path) -> list[Path]:
    """Return downloaded LAZ/COPC tiles."""

    return sorted((root / "data" / "raw" / "lidar" / "laz").glob("*.laz"))


def output_profile(template: rasterio.DatasetReader, dtype: str = "float32") -> dict:
    """Create a tiled, compressed GeoTIFF profile matching the DEM."""

    profile = template.profile.copy()
    profile.update(
        driver="GTiff",
        dtype=dtype,
        count=1,
        nodata=NODATA,
        compress="deflate",
        predictor=3,
        tiled=True,
        blockxsize=512,
        blockysize=512,
        BIGTIFF="YES",
    )
    return profile


def initialize_outputs(template_path: Path, outputs: dict[str, Path], force: bool) -> None:
    """Initialize DSM/building rasters from DEM and tree rasters from zero."""

    with rasterio.open(template_path) as dem:
        profile = output_profile(dem)
        for name, path in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and not force:
                print(f"exists: {path}")
                continue
            print(f"initialize: {name} -> {path}")
            with rasterio.open(path, "w", **profile) as dst:
                for _idx, window in dem.block_windows(1):
                    dem_block = dem.read(1, window=window).astype("float32")
                    valid = dem_block != dem.nodata
                    if name in {"dsm", "building_dsm"}:
                        out = dem_block
                    else:
                        out = np.full(dem_block.shape, NODATA, dtype="float32")
                        out[valid] = 0.0
                    dst.write(out, 1, window=window)


def _transformer_for_laz(laz_path: Path, target_crs: CRS) -> Transformer:
    with laspy.open(laz_path) as reader:
        source_crs = reader.header.parse_crs()
    if source_crs is None:
        source_crs = CRS.from_epsg(6318)
    return Transformer.from_crs(source_crs, target_crs, always_xy=True)


def _row_col(transform, xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    cols = np.floor((xs - transform.c) / transform.a).astype(np.int64)
    rows = np.floor((ys - transform.f) / transform.e).astype(np.int64)
    return rows, cols


def _window_from_rows_cols(rows: np.ndarray, cols: np.ndarray, height: int, width: int) -> Window | None:
    if rows.size == 0:
        return None
    row_min = max(0, int(rows.min()))
    row_max = min(height - 1, int(rows.max()))
    col_min = max(0, int(cols.min()))
    col_max = min(width - 1, int(cols.max()))
    if row_min > row_max or col_min > col_max:
        return None
    return Window(col_min, row_min, col_max - col_min + 1, row_max - row_min + 1)


def _update_window(
    datasets: dict[str, rasterio.io.DatasetWriter],
    dem: rasterio.DatasetReader,
    rows: np.ndarray,
    cols: np.ndarray,
    z: np.ndarray,
    classification: np.ndarray,
) -> tuple[int, int, int]:
    window = _window_from_rows_cols(rows, cols, dem.height, dem.width)
    if window is None:
        return 0, 0, 0

    row_off = int(window.row_off)
    col_off = int(window.col_off)
    local_rows = rows - row_off
    local_cols = cols - col_off

    dem_block = dem.read(1, window=window).astype("float32")
    valid_dem = dem_block != dem.nodata
    point_dem = dem_block[local_rows, local_cols]
    valid_points = point_dem != dem.nodata
    if not np.any(valid_points):
        return 0, 0, 0

    local_rows = local_rows[valid_points]
    local_cols = local_cols[valid_points]
    z = z[valid_points].astype("float32")
    classification = classification[valid_points]
    point_dem = point_dem[valid_points]

    dsm = datasets["dsm"].read(1, window=window).astype("float32")
    surface_mask = ~np.isin(classification, list(EXCLUDED_SURFACE_CLASSES))
    np.maximum.at(dsm, (local_rows[surface_mask], local_cols[surface_mask]), z[surface_mask])
    dsm[~valid_dem] = NODATA
    datasets["dsm"].write(dsm, 1, window=window)

    building = datasets["building_dsm"].read(1, window=window).astype("float32")
    building_mask = classification == BUILDING_CLASS
    if np.any(building_mask):
        np.maximum.at(building, (local_rows[building_mask], local_cols[building_mask]), z[building_mask])
    building[~valid_dem] = NODATA
    datasets["building_dsm"].write(building, 1, window=window)

    tree_height = datasets["trees_cdsm"].read(1, window=window).astype("float32")
    canopy_height = datasets["canopy_height"].read(1, window=window).astype("float32")
    vegetation_mask = np.isin(classification, list(VEGETATION_CLASSES))
    if np.any(vegetation_mask):
        heights = np.maximum(0.0, z[vegetation_mask] - point_dem[vegetation_mask])
        rr = local_rows[vegetation_mask]
        cc = local_cols[vegetation_mask]
        np.maximum.at(tree_height, (rr, cc), heights)
        np.maximum.at(canopy_height, (rr, cc), heights)
    tree_height[~valid_dem] = NODATA
    canopy_height[~valid_dem] = NODATA
    datasets["trees_cdsm"].write(tree_height, 1, window=window)
    datasets["canopy_height"].write(canopy_height, 1, window=window)

    return int(valid_points.sum()), int(building_mask.sum()), int(vegetation_mask.sum())


def process_tile(
    laz_path: Path,
    dem_path: Path,
    outputs: dict[str, Path],
    *,
    chunk_size: int,
) -> TileResult:
    """Rasterize one COPC LAZ tile into the output grids."""

    print(f"process: {laz_path.name}")
    with rasterio.open(dem_path) as dem:
        transformer = _transformer_for_laz(laz_path, dem.crs)
        with (
            rasterio.open(outputs["dsm"], "r+") as dsm,
            rasterio.open(outputs["building_dsm"], "r+") as building_dsm,
            rasterio.open(outputs["trees_cdsm"], "r+") as trees_cdsm,
            rasterio.open(outputs["canopy_height"], "r+") as canopy_height,
            laspy.open(laz_path) as reader,
        ):
            datasets = {
                "dsm": dsm,
                "building_dsm": building_dsm,
                "trees_cdsm": trees_cdsm,
                "canopy_height": canopy_height,
            }
            chunks = 0
            points_seen = 0
            points_used = 0
            building_points = 0
            vegetation_points = 0
            for points in reader.chunk_iterator(chunk_size):
                chunks += 1
                points_seen += len(points)
                xs, ys = transformer.transform(np.asarray(points.x), np.asarray(points.y))
                rows, cols = _row_col(dem.transform, np.asarray(xs), np.asarray(ys))
                in_bounds = (rows >= 0) & (rows < dem.height) & (cols >= 0) & (cols < dem.width)
                if not np.any(in_bounds):
                    continue
                used, buildings, vegetation = _update_window(
                    datasets,
                    dem,
                    rows[in_bounds],
                    cols[in_bounds],
                    np.asarray(points.z)[in_bounds],
                    np.asarray(points.classification)[in_bounds],
                )
                points_used += used
                building_points += buildings
                vegetation_points += vegetation

    return TileResult(
        path=str(laz_path),
        chunks=chunks,
        points_seen=points_seen,
        points_used=points_used,
        building_points=building_points,
        vegetation_points=vegetation_points,
    )


def write_metadata(root: Path, results: list[TileResult], outputs: dict[str, Path]) -> None:
    """Record LiDAR rasterization metadata."""

    path = root / "data" / "metadata" / "lidar_processing_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "classification_mapping": {
            "building": BUILDING_CLASS,
            "vegetation": sorted(VEGETATION_CLASSES),
            "excluded_surface_classes": sorted(EXCLUDED_SURFACE_CLASSES),
        },
        "outputs": {name: str(path) for name, path in outputs.items()},
        "tiles_processed": len(results),
        "results": [asdict(result) for result in results],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"metadata: {path}")


def already_processed_tiles(root: Path) -> set[str]:
    """Return tile paths already recorded in the processing manifest."""

    path = root / "data" / "metadata" / "lidar_processing_manifest.json"
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {result["path"] for result in payload.get("results", []) if "path" in result}


def existing_results(root: Path) -> list[TileResult]:
    """Return previous manifest results, if any."""

    path = root / "data" / "metadata" / "lidar_processing_manifest.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [TileResult(**item) for item in payload.get("results", [])]
    except Exception:
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--force-init", action="store_true", help="Reinitialize output rasters from DEM.")
    parser.add_argument("--max-tiles", type=int, default=None, help="Process only the first N downloaded LAZ tiles.")
    parser.add_argument(
        "--process-already-recorded",
        action="store_true",
        help="Reprocess tiles already listed in the manifest.",
    )
    parser.add_argument("--chunk-size", type=int, default=1_000_000)
    args = parser.parse_args()

    root = args.root.resolve()
    dem_path = root / "data" / "processed" / "rasters" / "dem_1m.tif"
    if not dem_path.exists():
        raise FileNotFoundError(f"Missing DEM: {dem_path}")

    outputs = {
        "dsm": root / "data" / "processed" / "solweig_inputs" / "dsm_1m.tif",
        "building_dsm": root / "data" / "processed" / "solweig_inputs" / "building_dsm_1m.tif",
        "trees_cdsm": root / "data" / "processed" / "solweig_inputs" / "trees_cdsm_1m.tif",
        "canopy_height": root / "data" / "processed" / "rasters" / "canopy_height_1m.tif",
    }
    initialize_outputs(dem_path, outputs, force=args.force_init)

    tiles = laz_files(root)
    if args.max_tiles is not None:
        tiles = tiles[: args.max_tiles]
    prior_results = [] if args.force_init else existing_results(root)
    if not args.force_init and not args.process_already_recorded:
        done = already_processed_tiles(root)
        tiles = [tile for tile in tiles if str(tile) not in done]
    if not tiles:
        print("no unprocessed LAZ/COPC tiles found")
        return 0

    results = prior_results + [process_tile(tile, dem_path, outputs, chunk_size=args.chunk_size) for tile in tiles]
    write_metadata(root, results, outputs)
    print(f"processed {len(results)} tile(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
