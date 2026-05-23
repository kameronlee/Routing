"""Run SOLWEIG-GPU against the prepared Washington, D.C. raster bundle.

This script is a thin orchestration layer around ``solweig_gpu.thermal_comfort``.
It can run the full-city rasters, or create a small clipped real-data subset for
environment validation before committing to the longer production run.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import shutil

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.windows import from_bounds
from rasterio.warp import transform as warp_transform


@dataclass(frozen=True)
class SolweigInputs:
    """SOLWEIG raster inputs with matching grid geometry."""

    building_dsm: Path
    dem: Path
    trees: Path


def parse_metfile_hours(met_file: Path) -> list[int]:
    """Return the local hour column from a SOLWEIG/UMEP metfile."""

    rows = met_file.read_text(encoding="utf-8").splitlines()[1:]
    return [int(row.split()[2]) for row in rows if row.strip()]


def filter_metfile_to_hour(source: Path, destination: Path, hour: int | None) -> Path:
    """Copy a SOLWEIG metfile, optionally keeping only one local hour."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = source.read_text(encoding="utf-8").splitlines()
    if hour is None:
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return destination

    header, rows = lines[0], lines[1:]
    kept = [row for row in rows if row.strip() and int(row.split()[2]) == hour]
    if not kept:
        raise ValueError(f"No hour {hour:02d} found in metfile {source}")
    destination.write_text("\n".join([header, *kept]) + "\n", encoding="utf-8")
    return destination


def _clip_raster(source: Path, destination: Path, center_lat: float, center_lon: float, size_m: float) -> None:
    """Clip a raster to a square around a WGS84 center point."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(source) as dataset:
        xs, ys = warp_transform("EPSG:4326", dataset.crs, [center_lon], [center_lat])
        center_x = xs[0]
        center_y = ys[0]
        half = size_m / 2.0
        window = from_bounds(
            center_x - half,
            center_y - half,
            center_x + half,
            center_y + half,
            transform=dataset.transform,
        ).round_offsets().round_lengths()
        data = dataset.read(window=window, boundless=False)
        profile = dataset.profile.copy()
        profile.update(
            height=data.shape[1],
            width=data.shape[2],
            transform=dataset.window_transform(window),
            BIGTIFF="YES",
        )
        with rasterio.open(destination, "w", **profile) as output:
            output.write(data)


def prepare_inputs(
    root: Path,
    work_dir: Path,
    *,
    subset_size_m: float | None,
    center_lat: float,
    center_lon: float,
) -> SolweigInputs:
    """Return full-city inputs or clipped real-data smoke-test inputs."""

    full = SolweigInputs(
        building_dsm=root / "data" / "processed" / "solweig_inputs" / "building_dsm_1m.tif",
        dem=root / "data" / "processed" / "solweig_inputs" / "dem_1m.tif",
        trees=root / "data" / "processed" / "solweig_inputs" / "trees_cdsm_1m.tif",
    )
    for path in (full.building_dsm, full.dem, full.trees):
        if not path.exists():
            raise FileNotFoundError(f"Missing SOLWEIG input raster: {path}")

    if subset_size_m is None:
        return full

    subset_dir = work_dir / "subset_inputs"
    subset = SolweigInputs(
        building_dsm=subset_dir / "Building_DSM.tif",
        dem=subset_dir / "DEM.tif",
        trees=subset_dir / "Trees.tif",
    )
    _clip_raster(full.building_dsm, subset.building_dsm, center_lat, center_lon, subset_size_m)
    _clip_raster(full.dem, subset.dem, center_lat, center_lon, subset_size_m)
    _clip_raster(full.trees, subset.trees, center_lat, center_lon, subset_size_m)
    return subset


def _output_times(selected_date: date, met_file: Path) -> list[tuple[int, str]]:
    hours = parse_metfile_hours(met_file)
    return [(index + 1, f"{selected_date.isoformat()}_{hour:02d}") for index, hour in enumerate(hours)]


def publish_solweig_outputs(work_dir: Path, output_dir: Path, selected_date: date, met_file: Path) -> list[Path]:
    """Merge SOLWEIG tile outputs and publish one GeoTIFF per metfile hour."""

    tile_paths = sorted((work_dir / "output_folder").glob("*/UTCI_*.tif"))
    if not tile_paths:
        raise FileNotFoundError(f"No SOLWEIG UTCI tile outputs found under {work_dir / 'output_folder'}")

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    times = _output_times(selected_date, met_file)
    for band_index, timestamp in times:
        datasets = [rasterio.open(path) for path in tile_paths]
        try:
            mosaic, transform = merge(datasets, indexes=band_index)
            profile = datasets[0].profile.copy()
            profile.update(
                count=1,
                height=mosaic.shape[1],
                width=mosaic.shape[2],
                transform=transform,
                compress="deflate",
                predictor=3,
                tiled=True,
                BIGTIFF="YES",
            )
            destination = output_dir / f"utci_{timestamp}.tif"
            with rasterio.open(destination, "w", **profile) as output:
                output.write(mosaic[0], 1)
            written.append(destination)
        finally:
            for dataset in datasets:
                dataset.close()
    return written


def run_solweig(
    work_dir: Path,
    inputs: SolweigInputs,
    selected_date: date,
    met_file: Path,
    *,
    tile_size: int,
    overlap: int,
    save_tmrt: bool,
    save_shadow: bool,
) -> None:
    """Invoke SOLWEIG-GPU with explicit real input files."""

    try:
        from solweig_gpu import thermal_comfort
        import solweig_gpu.sun_position as sun_module
    except ImportError as exc:
        raise RuntimeError("Install the optional SOLWEIG stack with `pip install -e .[solweig]`.") from exc

    original_loadtxt = np.loadtxt
    original_sun_position = sun_module.sun_position

    def loadtxt_2d(*args, **kwargs):
        if args and "metfile_" in Path(str(args[0])).name:
            kwargs.setdefault("ndmin", 2)
        return original_loadtxt(*args, **kwargs)

    def scalar_sun_position(*args, **kwargs):
        result = original_sun_position(*args, **kwargs)
        for key, value in list(result.items()):
            if isinstance(value, np.ndarray) and value.size == 1:
                result[key] = float(value.ravel()[0])
        return result

    np.loadtxt = loadtxt_2d
    sun_module.sun_position = scalar_sun_position
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        thermal_comfort(
            base_path=str(work_dir),
            selected_date_str=selected_date.isoformat(),
            building_dsm_filename=str(inputs.building_dsm),
            dem_filename=str(inputs.dem),
            trees_filename=str(inputs.trees),
            landcover_filename=None,
            tile_size=tile_size,
            overlap=overlap,
            use_own_met=True,
            own_met_file=str(met_file),
            save_tmrt=save_tmrt,
            save_shadow=save_shadow,
        )
    finally:
        np.loadtxt = original_loadtxt
        sun_module.sun_position = original_sun_position


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--met-file", type=Path, required=True)
    parser.add_argument("--hour", type=int, default=None, choices=range(24))
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--subset-size-m", type=float, default=None)
    parser.add_argument("--subset-center-lat", type=float, default=38.9072)
    parser.add_argument("--subset-center-lon", type=float, default=-77.0369)
    parser.add_argument("--tile-size", type=int, default=1000)
    parser.add_argument("--overlap", type=int, default=20)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--save-tmrt", action="store_true")
    parser.add_argument("--save-shadow", action="store_true")
    parser.add_argument("--clean-work-dir", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    work_dir = args.work_dir or root / "data" / "processed" / "solweig_gpu_work"
    work_dir = work_dir.resolve()
    if args.clean_work_dir and work_dir.exists():
        shutil.rmtree(work_dir)

    met_file = filter_metfile_to_hour(
        args.met_file.resolve(),
        work_dir / "metfiles" / f"met_forcing_{args.date.isoformat()}_{args.hour if args.hour is not None else 'all'}.txt",
        args.hour,
    )
    inputs = prepare_inputs(
        root,
        work_dir,
        subset_size_m=args.subset_size_m,
        center_lat=args.subset_center_lat,
        center_lon=args.subset_center_lon,
    )
    run_solweig(
        work_dir,
        inputs,
        args.date,
        met_file,
        tile_size=args.tile_size,
        overlap=args.overlap,
        save_tmrt=args.save_tmrt,
        save_shadow=args.save_shadow,
    )
    if args.publish:
        written = publish_solweig_outputs(
            work_dir,
            root / "data" / "processed" / "solweig_outputs",
            args.date,
            met_file,
        )
        for path in written:
            print(f"published: {path}")
    else:
        print(f"solweig outputs: {work_dir / 'output_folder'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
