#!/usr/bin/env python
"""Inspect UTCI and direct-shadow rasters for a snapshot experiment."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routing_backend.experiment_config import load_experiment_config
from routing_backend.experiment_io import ensure_output_layout, write_csv, write_json, write_markdown
from routing_backend.raster_validation import (
    compute_raster_stats,
    sample_paired_utci_shadow_cells,
    save_raster_overview_png,
    save_shaded_sunlit_boxplot_png,
    save_utci_shadow_overlay_png,
    validate_raster_pair,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to experiment YAML/JSON config.")
    parser.add_argument("--output-dir", help="Optional output directory override.")
    parser.add_argument("--sample-count", type=int, default=100_000, help="Paired UTCI/shadow samples.")
    args = parser.parse_args()

    config = load_experiment_config(args.config)
    if args.output_dir:
        config = config.__class__(**{**config.__dict__, "output_dir": Path(args.output_dir).resolve()})
    ensure_output_layout(config)
    for name, path in {"utci_raster_path": config.utci_raster_path, "shadow_raster_path": config.shadow_raster_path}.items():
        if not path.exists():
            raise FileNotFoundError(f"{name} does not exist: {path}")

    report = validate_raster_pair(
        config.utci_raster_path,
        config.shadow_raster_path,
        sample_count=args.sample_count,
        seed=config.random_seed,
    )
    write_json(config.output_dir / "raster_metadata.json", report["metadata"])
    stats_rows = [
        {"raster": "utci", **compute_raster_stats(config.utci_raster_path)},
        {"raster": "shadow", **compute_raster_stats(config.shadow_raster_path)},
    ]
    write_csv(config.output_dir / "raster_stats.csv", stats_rows)
    figure_warning = _write_figures_if_available(config, args.sample_count)
    write_markdown(config.output_dir / "raster_alignment_report.md", _alignment_markdown(config, report, figure_warning))


def _write_figures_if_available(config, sample_count: int) -> str | None:
    try:
        import matplotlib.pyplot  # noqa: F401
    except ImportError:
        return "Raster PNG figures were skipped because matplotlib is not installed. Install with `python -m pip install -e \".[experiments]\"`."

    paired = sample_paired_utci_shadow_cells(
        config.utci_raster_path,
        config.shadow_raster_path,
        max_samples=sample_count,
        seed=config.random_seed,
    )
    save_raster_overview_png(
        config.utci_raster_path,
        config.output_dir / "figures" / "utci_raster_overview.png",
        title="UTCI raster overview",
        cmap="inferno",
    )
    save_raster_overview_png(
        config.shadow_raster_path,
        config.output_dir / "figures" / "shadow_raster_overview.png",
        title="Direct-shadow raster overview",
        cmap="gray",
    )
    save_utci_shadow_overlay_png(
        config.utci_raster_path,
        config.shadow_raster_path,
        config.output_dir / "figures" / "utci_shadow_overlay.png",
    )
    save_shaded_sunlit_boxplot_png(
        paired.utci,
        paired.shadow,
        config.output_dir / "figures" / "utci_by_shadow_boxplot.png",
    )
    return None


def _alignment_markdown(config, report: dict, figure_warning: str | None = None) -> str:
    shadow = report["shadow_value_report"]
    shaded = report["shaded_vs_sunlit_utci"]
    warnings = list(report["warnings"])
    if figure_warning:
        warnings.append(figure_warning)
    if not warnings:
        warnings = ["No raster plausibility warnings were produced."]
    warning_lines = "\n".join(f"- {warning}" for warning in warnings)
    return f"""# Raster Plausibility Report: {config.study_name}

This is an internal consistency check for modeled UTCI and direct-shadow rasters. It is not field validation.

- UTCI raster: `{config.utci_raster_path}`
- Shadow raster: `{config.shadow_raster_path}`
- CRS match: {report["overlap"].get("crs_match")}
- Bounds overlap: {report["overlap"].get("overlap")}
- Paired sample count: {report["paired_sample_count"]}
- Shadow convention: {shadow.get("likely_convention")}
- Shadow near-0 count: {shadow.get("near_zero_count")}
- Shadow near-1 count: {shadow.get("near_one_count")}
- Shadow intermediate count: {shadow.get("intermediate_count")}
- Median UTCI in shaded cells: {shaded.get("median_utci_shaded")}
- Median UTCI in sunlit cells: {shaded.get("median_utci_sunlit")}
- Median shaded-minus-sunlit UTCI (C): {shaded.get("median_shaded_minus_sunlit_c")}

## Warnings

{warning_lines}
"""


if __name__ == "__main__":
    main()
