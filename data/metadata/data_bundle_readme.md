# Washington, DC inputs

The paper uses the versioned walking graph, UTCI/shadow fields, terrain,
canopy, land cover, and traffic layers named in
`configs/dc_snapshot_review3466.yaml`. Fetch the frozen files through Git LFS;
the experiment manifests record their checksums.

Source material includes Geofabrik OpenStreetMap extracts, DC GIS land cover
and traffic, NOAA-hosted DC OCTO 2022 LiDAR, and Open-Meteo weather forcing.
See `lidar_sources.md` and the individual metadata JSON files for source URLs.

The build scripts download or derive new products. They do not reconstruct
the original thermal field exactly: its retained provenance lacks the
forecast retrieval time, selected forecast model, and SOLWEIG release.
