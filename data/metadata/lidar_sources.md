# LiDAR Sources

This bundle stages NOAA-hosted DC OCTO 2022 LiDAR products.

- Point cloud URL list: `data/raw/lidar/urllist9837.txt`
- Sample COPC LAZ tile: `data/raw/lidar/laz/20220124_2916.copc.laz`
- Full-city 1 m DEM/DTM: `data/raw/lidar/dem_2022_tiles/DTM_2022_1m.tif`
- Processed DEM alias: `data/processed/rasters/dem_1m.tif`
- SOLWEIG DEM input alias: `data/processed/solweig_inputs/dem_1m.tif`

The NOAA DEM product is published in projected coordinates for the DC region.
The source metadata identifies NAD83 / Maryland-style projected horizontal
coordinates and NAVD88 vertical height where available.

The default downloader records all 335 raw point-cloud tile URLs but downloads
only one representative COPC LAZ tile. Run:

```bash
python scripts/build_dc_data_bundle.py --download-all-laz
```

to fetch the full point-cloud catalog. Expect a multi-GB download.
