# SOLWEIG inputs

The model runner uses aligned `building_dsm_1m.tif`, `dem_1m.tif`, and
`trees_cdsm_1m.tif`, with hourly meteorological forcing in UMEP metfile format.
The LiDAR sources and preparation steps are recorded under `data/metadata/`
and in `scripts/build_lidar_products.py`.

The building DSM contains absolute surface elevation. The routing height
proxy is a separate `max(0, DSM - DEM)` product made by
`scripts/derive_building_height.py`.

Frozen source files are stored through Git LFS. Their paths and checksums are
listed in the experiment manifests; local presence must be checked after
fetching them.
