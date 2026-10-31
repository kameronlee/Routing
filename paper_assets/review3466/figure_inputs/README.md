# Figure inputs

The two routes in `route_cases.geojson.gz` are a subset of the original
`dc_snapshot_500pair_main_methods/routes.geojson`. Their properties match the
archived summary CSV. `route_cases_source.json` records the full source hash
and selection rule: nearest observed paired H reduction to the median
among 309 common successful pairs at a 20% allowance, with
ties broken by OD ID. Coordinates were projected to EPSG:32618.

Background layers were retrieved on October 28, 2026:

- [Roadway Block](https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_WebMercator/MapServer/163): DDOT, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- [Waterbodies 2023](https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Planimetrics_2023/MapServer/14): DC OCTO/DC GIS.
- District boundary: the existing `data/raw/boundary/dc_boundary.geojson`.

These layers provide geographic context only. They are not the historical
routing graph or thermal/shadow fields. `sources.json` records query endpoints,
counts, attribution, and checksums. The default build uses these frozen files
without network access:

```bash
python experiments/make_geohealth_figures.py
```

Outputs are vector PDFs and 300 dpi PNG previews in `../analysis/`.
The route map uses a 1.7 by 1.4 km window. Exact shared geometry is drawn
once in gray; the remaining segments retain their coordinates. Street labels
follow the frozen DDOT geometry. The accompanying scatter plot includes all
309 common successful pairs at the same allowance. Runtime ECDFs
include all 10,000 attempts, split by method and acceptance status. Assertions
check the selected records, geometry/CSV agreement, histogram counts, complete
runtime range, and the 8 pt minimum label size at a 7 in figure width.
