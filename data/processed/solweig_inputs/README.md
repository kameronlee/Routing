# SOLWEIG Inputs

This directory is for rasters prepared for SOLWEIG or SOLWEIG-GPU.

Current staged inputs:

- `dem_1m.tif`: NOAA 2022 DC OCTO full-city DEM/DTM.
- `dsm_1m.tif`: full-city surface DSM rasterized from classified COPC LAZ tiles.
- `building_dsm_1m.tif`: full-city building-only DSM rasterized from class 6 points.
- `trees_cdsm_1m.tif`: full-city vegetation canopy DSM/raster height from classes 3, 4 and 5.
- `met_forcing_2026-05-23_2026-05-23.txt`: real Open-Meteo forcing in SOLWEIG metfile format.
- `landcover_1m_center_tile.tif`: DC 2020 generalized land-cover center tile.
- `trees_cdsm_1m_center_tile.tif`: DC 2020 urban tree canopy center tile.

Still needed for full-fidelity microclimate:

- Full production SOLWEIG/SOLWEIG-GPU run outputs in `data/processed/solweig_outputs/`.
