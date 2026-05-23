# SOLWEIG Outputs

Place real SOLWEIG or SOLWEIG-GPU outputs here.

Expected names:

```text
utci_YYYY-MM-DD_HH.tif
tmrt_YYYY-MM-DD_HH.tif
shadow_YYYY-MM-DD_HH.tif
```

The backend automatically searches this directory for the closest matching UTCI
GeoTIFF and samples it along edges/routes. In strict runtime mode, route
requests fail when no UTCI raster exists.

The SOLWEIG-GPU runner has been validated against a clipped real-data subset,
but the smoke-test files are kept under `data/processed/solweig_gpu_smoke` so
they do not make the API look production-ready for all of DC. Run
`scripts/run_solweig_gpu.py --publish` after a production run to write canonical
UTCI files here.
