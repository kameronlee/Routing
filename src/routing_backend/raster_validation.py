"""Raster plausibility and alignment checks for snapshot experiments."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import random
from statistics import fmean, median
from typing import Any, Sequence


@dataclass(frozen=True)
class PairedShadowUtciSamples:
    """Paired UTCI and shadow samples drawn from the overlapping raster area."""

    utci: tuple[float, ...]
    shadow: tuple[float, ...]


def _valid_values_from_masked_array(data: Any, nodata: float | None) -> Any:
    """Return finite, non-nodata values from a rasterio masked read."""

    import numpy as np

    if nodata is not None:
        data = np.ma.masked_equal(data, nodata)
    values = np.asarray(data.compressed(), dtype=float)
    return values[np.isfinite(values)]


def load_raster_metadata(path: str | Path) -> dict[str, Any]:
    """Return basic GeoTIFF metadata."""

    import rasterio

    raster_path = Path(path)
    with rasterio.open(raster_path) as dataset:
        return {
            "path": str(raster_path),
            "driver": dataset.driver,
            "width": dataset.width,
            "height": dataset.height,
            "count": dataset.count,
            "dtype": dataset.dtypes[0] if dataset.dtypes else None,
            "crs": str(dataset.crs) if dataset.crs else None,
            "bounds": {
                "left": dataset.bounds.left,
                "bottom": dataset.bounds.bottom,
                "right": dataset.bounds.right,
                "top": dataset.bounds.top,
            },
            "resolution": {"x": abs(dataset.transform.a), "y": abs(dataset.transform.e)},
            "nodata": dataset.nodata,
        }


def compute_raster_stats(path: str | Path, *, max_quantile_samples: int = 1_000_000) -> dict[str, Any]:
    """Compute raster statistics for the first band without loading huge rasters at once.

    Min, max, mean, and counts are exact. Percentiles are exact for rasters with
    at most ``max_quantile_samples`` cells and deterministic downsampled
    estimates for larger rasters.
    """

    import numpy as np
    import rasterio

    raster_path = Path(path)
    with rasterio.open(raster_path) as dataset:
        total_cells = dataset.width * dataset.height
        sample_stride = max(1, math.ceil(total_cells / max(1, max_quantile_samples)))
        valid_count = 0
        total_count = 0
        value_sum = 0.0
        minimum: float | None = None
        maximum: float | None = None
        quantile_values: list[np.ndarray] = []
        sampled_count = 0
        for _block_index, window in dataset.block_windows(1):
            data = dataset.read(1, window=window, masked=True)
            values = _valid_values_from_masked_array(data, dataset.nodata)
            total_count += int(data.size)
            if values.size == 0:
                continue
            valid_count += int(values.size)
            value_sum += float(np.sum(values))
            block_min = float(np.min(values))
            block_max = float(np.max(values))
            minimum = block_min if minimum is None else min(minimum, block_min)
            maximum = block_max if maximum is None else max(maximum, block_max)
            sampled = values[::sample_stride]
            if sampled.size:
                remaining = max_quantile_samples - sampled_count
                if remaining > 0:
                    quantile_values.append(sampled[:remaining])
                    sampled_count += int(min(sampled.size, remaining))

    if valid_count == 0:
        return {
            "path": str(raster_path),
            "valid_count": 0,
            "nodata_count": total_count,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "p5": None,
            "p25": None,
            "p75": None,
            "p95": None,
            "quantile_sample_count": 0,
            "quantiles_approximate": False,
        }
    quantiles = np.concatenate(quantile_values) if quantile_values else np.array([], dtype=float)
    return {
        "path": str(raster_path),
        "valid_count": int(valid_count),
        "nodata_count": int(total_count - valid_count),
        "min": minimum,
        "max": maximum,
        "mean": value_sum / valid_count,
        "median": float(np.median(quantiles)) if quantiles.size else None,
        "p5": float(np.percentile(quantiles, 5)) if quantiles.size else None,
        "p25": float(np.percentile(quantiles, 25)) if quantiles.size else None,
        "p75": float(np.percentile(quantiles, 75)) if quantiles.size else None,
        "p95": float(np.percentile(quantiles, 95)) if quantiles.size else None,
        "quantile_sample_count": int(quantiles.size),
        "quantiles_approximate": sample_stride > 1,
    }


def analyze_shadow_values(path: str | Path) -> dict[str, Any]:
    """Analyze likely shadow-raster value convention."""

    import numpy as np
    import rasterio

    valid_count = 0
    near_zero = 0
    near_one = 0
    with rasterio.open(path) as dataset:
        for _block_index, window in dataset.block_windows(1):
            data = dataset.read(1, window=window, masked=True)
            values = _valid_values_from_masked_array(data, dataset.nodata)
            if values.size == 0:
                continue
            valid_count += int(values.size)
            near_zero += int(np.sum(np.isclose(values, 0.0, atol=0.05)))
            near_one += int(np.sum(np.isclose(values, 1.0, atol=0.05)))
    intermediate = int(valid_count - near_zero - near_one)
    likely = "unknown"
    if valid_count and (near_zero + near_one) / valid_count >= 0.8:
        likely = "direct_solweig_shadow_0_shade_1_sun"
    return {
        "valid_count": int(valid_count),
        "near_zero_count": near_zero,
        "near_one_count": near_one,
        "intermediate_count": intermediate,
        "near_zero_fraction": near_zero / valid_count if valid_count else None,
        "near_one_fraction": near_one / valid_count if valid_count else None,
        "likely_convention": likely,
    }


def compute_overlap_bounds(utci_path: str | Path, shadow_path: str | Path) -> dict[str, Any]:
    """Return bounding-box overlap after transforming shadow bounds into UTCI CRS."""

    import rasterio
    from rasterio.warp import transform_bounds

    with rasterio.open(utci_path) as utci, rasterio.open(shadow_path) as shadow:
        if utci.crs is None or shadow.crs is None:
            return {
                "crs_match": utci.crs == shadow.crs,
                "can_transform": False,
                "overlap": False,
                "message": "One or both rasters lack a CRS.",
            }
        try:
            shadow_bounds = transform_bounds(shadow.crs, utci.crs, *shadow.bounds)
            can_transform = True
        except Exception as exc:
            return {
                "crs_match": utci.crs == shadow.crs,
                "can_transform": False,
                "overlap": False,
                "message": f"Could not transform bounds: {exc}",
            }
        left = max(utci.bounds.left, shadow_bounds[0])
        bottom = max(utci.bounds.bottom, shadow_bounds[1])
        right = min(utci.bounds.right, shadow_bounds[2])
        top = min(utci.bounds.top, shadow_bounds[3])
        overlap = left < right and bottom < top
        return {
            "crs_match": utci.crs == shadow.crs,
            "can_transform": can_transform,
            "overlap": overlap,
            "utci_crs": str(utci.crs),
            "shadow_crs": str(shadow.crs),
            "overlap_bounds_in_utci_crs": {
                "left": left,
                "bottom": bottom,
                "right": right,
                "top": top,
            }
            if overlap
            else None,
            "overlap_area_in_utci_crs_units": (right - left) * (top - bottom) if overlap else 0.0,
        }


def sample_paired_utci_shadow_cells(
    utci_path: str | Path,
    shadow_path: str | Path,
    *,
    max_samples: int = 100_000,
    seed: int = 42,
) -> PairedShadowUtciSamples:
    """Sample paired UTCI/shadow cells from the overlapping bounds."""

    import rasterio
    from rasterio.warp import transform

    overlap_info = compute_overlap_bounds(utci_path, shadow_path)
    bounds = overlap_info.get("overlap_bounds_in_utci_crs")
    if not bounds:
        return PairedShadowUtciSamples(utci=(), shadow=())

    rng = random.Random(seed)
    with rasterio.open(utci_path) as utci, rasterio.open(shadow_path) as shadow:
        sample_count = max(1, int(max_samples))
        xs = [rng.uniform(bounds["left"], bounds["right"]) for _idx in range(sample_count)]
        ys = [rng.uniform(bounds["bottom"], bounds["top"]) for _idx in range(sample_count)]
        if utci.crs != shadow.crs:
            shadow_xs, shadow_ys = transform(utci.crs, shadow.crs, xs, ys)
        else:
            shadow_xs, shadow_ys = xs, ys

        utci_values: list[float] = []
        shadow_values: list[float] = []
        utci_nodata = utci.nodata
        shadow_nodata = shadow.nodata
        for utci_sample, shadow_sample in zip(utci.sample(zip(xs, ys)), shadow.sample(zip(shadow_xs, shadow_ys))):
            if len(utci_sample) == 0 or len(shadow_sample) == 0:
                continue
            utci_value = float(utci_sample[0])
            shadow_value = float(shadow_sample[0])
            if utci_nodata is not None and utci_value == float(utci_nodata):
                continue
            if shadow_nodata is not None and shadow_value == float(shadow_nodata):
                continue
            if math.isfinite(utci_value) and math.isfinite(shadow_value):
                utci_values.append(utci_value)
                shadow_values.append(shadow_value)
    return PairedShadowUtciSamples(utci=tuple(utci_values), shadow=tuple(shadow_values))


def compare_shaded_vs_sunlit_utci(
    utci_values: Sequence[float],
    shadow_values: Sequence[float],
    *,
    shade_threshold: float = 0.5,
) -> dict[str, Any]:
    """Compare UTCI distributions under direct shade and sunlit cells."""

    shaded = [utci for utci, shadow in zip(utci_values, shadow_values) if shadow <= shade_threshold]
    sunlit = [utci for utci, shadow in zip(utci_values, shadow_values) if shadow > shade_threshold]
    shaded_median = median(shaded) if shaded else None
    sunlit_median = median(sunlit) if sunlit else None
    shaded_mean = fmean(shaded) if shaded else None
    sunlit_mean = fmean(sunlit) if sunlit else None
    warnings: list[str] = []
    if shaded_median is not None and sunlit_median is not None and shaded_median >= sunlit_median:
        warnings.append("Median UTCI in shaded cells is not lower than median UTCI in sunlit cells.")
    return {
        "shaded_count": len(shaded),
        "sunlit_count": len(sunlit),
        "median_utci_shaded": shaded_median,
        "median_utci_sunlit": sunlit_median,
        "mean_utci_shaded": shaded_mean,
        "mean_utci_sunlit": sunlit_mean,
        "median_shaded_minus_sunlit_c": (
            shaded_median - sunlit_median if shaded_median is not None and sunlit_median is not None else None
        ),
        "warnings": warnings,
    }


def validate_raster_pair(
    utci_path: str | Path,
    shadow_path: str | Path,
    *,
    sample_count: int = 100_000,
    seed: int = 42,
) -> dict[str, Any]:
    """Run internal-consistency checks for UTCI and direct-shadow rasters."""

    metadata = {
        "utci": load_raster_metadata(utci_path),
        "shadow": load_raster_metadata(shadow_path),
    }
    stats = {
        "utci": compute_raster_stats(utci_path),
        "shadow": compute_raster_stats(shadow_path),
    }
    overlap = compute_overlap_bounds(utci_path, shadow_path)
    paired = sample_paired_utci_shadow_cells(utci_path, shadow_path, max_samples=sample_count, seed=seed)
    shadow_report = analyze_shadow_values(shadow_path)
    shaded_report = compare_shaded_vs_sunlit_utci(paired.utci, paired.shadow)
    warnings: list[str] = []
    if not overlap.get("overlap"):
        warnings.append("UTCI and shadow rasters do not overlap.")
    if not overlap.get("crs_match"):
        warnings.append("UTCI and shadow raster CRS differ; sampling used coordinate transformation.")
    warnings.extend(shaded_report["warnings"])
    return {
        "metadata": metadata,
        "stats": stats,
        "overlap": overlap,
        "shadow_value_report": shadow_report,
        "shaded_vs_sunlit_utci": shaded_report,
        "paired_sample_count": len(paired.utci),
        "warnings": warnings,
    }


def save_raster_overview_png(path: str | Path, output_path: str | Path, *, title: str, cmap: str = "viridis") -> None:
    """Save a single-band raster overview PNG."""

    import matplotlib.pyplot as plt
    import rasterio
    from rasterio.enums import Resampling

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path) as dataset:
        out_shape = _overview_shape(dataset)
        data = dataset.read(1, out_shape=out_shape, masked=True, resampling=Resampling.average)
    fig, ax = plt.subplots(figsize=(7, 6), constrained_layout=True)
    image = ax.imshow(data, cmap=cmap)
    ax.set_title(title)
    ax.set_xlabel("column")
    ax.set_ylabel("row")
    fig.colorbar(image, ax=ax, shrink=0.8)
    fig.savefig(output, dpi=200)
    plt.close(fig)


def save_utci_shadow_overlay_png(utci_path: str | Path, shadow_path: str | Path, output_path: str | Path) -> None:
    """Save a quick UTCI raster with shaded cells overlaid when grids align."""

    import matplotlib.pyplot as plt
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(utci_path) as utci, rasterio.open(shadow_path) as shadow:
        out_shape = _overview_shape(utci)
        utci_data = utci.read(1, out_shape=out_shape, masked=True, resampling=Resampling.average)
        shadow_data = shadow.read(1, out_shape=out_shape, masked=True, resampling=Resampling.nearest)
        same_grid = utci.shape == shadow.shape and utci.transform == shadow.transform and utci.crs == shadow.crs

    fig, ax = plt.subplots(figsize=(7, 6), constrained_layout=True)
    image = ax.imshow(utci_data, cmap="inferno")
    fig.colorbar(image, ax=ax, shrink=0.8, label="UTCI (C)")
    if same_grid:
        shade_mask = np.ma.masked_where(np.asarray(shadow_data) > 0.5, np.ones_like(np.asarray(shadow_data)))
        ax.imshow(shade_mask, cmap="Blues", alpha=0.35)
        ax.set_title("UTCI with direct-shadow cells overlaid")
    else:
        ax.set_title("UTCI raster (shadow grid differs; see alignment report)")
    ax.set_xlabel("column")
    ax.set_ylabel("row")
    fig.savefig(output, dpi=200)
    plt.close(fig)


def _overview_shape(dataset: Any, *, max_size: int = 1600) -> tuple[int, int]:
    """Return an aspect-preserving raster overview shape."""

    scale = min(1.0, max_size / max(dataset.height, dataset.width))
    height = max(1, int(round(dataset.height * scale)))
    width = max(1, int(round(dataset.width * scale)))
    return height, width


def save_shaded_sunlit_boxplot_png(
    utci_values: Sequence[float],
    shadow_values: Sequence[float],
    output_path: str | Path,
) -> None:
    """Save a UTCI boxplot split by direct-shadow value."""

    import matplotlib.pyplot as plt

    shaded = [utci for utci, shadow in zip(utci_values, shadow_values) if shadow <= 0.5]
    sunlit = [utci for utci, shadow in zip(utci_values, shadow_values) if shadow > 0.5]
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 5), constrained_layout=True)
    try:
        ax.boxplot([shaded, sunlit], tick_labels=["shade", "sun"])
    except TypeError as exc:
        if "tick_labels" not in str(exc):
            raise
        ax.boxplot([shaded, sunlit], labels=["shade", "sun"])
    ax.set_title("UTCI by direct-shadow class")
    ax.set_ylabel("UTCI (C)")
    fig.savefig(output, dpi=200)
    plt.close(fig)
