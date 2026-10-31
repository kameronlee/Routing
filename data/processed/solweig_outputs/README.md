# Modeled thermal fields

The paper uses `utci_2026-06-19_14.tif` and `shadow_2026-06-19_14.tif`, stored
through Git LFS. These are one modeled Washington, DC hour. The configuration
selects their exact paths; manifests record the raster checksums and grids.

New hourly products use `utci_YYYY-MM-DD_HH.tif` and
`shadow_YYYY-MM-DD_HH.tif`. `scripts/run_solweig_gpu.py --publish` writes these
files after a model run. Each additional hour needs its own modeled fields.
