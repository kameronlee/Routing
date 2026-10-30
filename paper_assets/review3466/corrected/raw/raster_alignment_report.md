# Raster Plausibility Report: dc_snapshot_review3466

This is an internal consistency check for modeled UTCI and direct-shadow rasters. It is not field validation.

- UTCI raster: `/scratch/klee206/work/Routing/.codex/review3466-final-20261029/data/processed/solweig_outputs/utci_2026-06-19_14.tif`
- Shadow raster: `/scratch/klee206/work/Routing/.codex/review3466-final-20261029/data/processed/solweig_outputs/shadow_2026-06-19_14.tif`
- CRS match: True
- Bounds overlap: True
- Paired sample count: 10000
- Shadow convention: direct_solweig_shadow_0_shade_1_sun
- Shadow near-0 count: 80097255
- Shadow near-1 count: 380702745
- Shadow intermediate count: 0
- Median UTCI in shaded cells: 26.140165328979492
- Median UTCI in sunlit cells: 32.97793197631836
- Median shaded-minus-sunlit UTCI (C): -6.837766647338867

## Warnings

- No raster plausibility warnings were produced.
