# Methods Template

## Graph Construction

The routing graph is loaded from a real OSM/GraphML walking network. Edges store
length and geometry; node elevations may be sampled from a LiDAR-derived DEM.

## Raster Alignment

UTCI and direct-shadow GeoTIFFs are checked for readable CRS, bounds, resolution,
NoData values, and overlapping coverage. If CRS differs, coordinates are
transformed before paired sampling.

## Edge Sampling

Each edge geometry is densified at the configured spacing. UTCI and direct-shadow
values are sampled at densified points. Edge-level metrics are aggregated by
length when routes are summarized.

## UTCI Metric

Modeled UTCI is reported as mean UTCI, maximum UTCI, and route-level reductions
relative to the shortest-distance route for the same OD pair and detour setting.

## Direct-Shadow Metric

The direct-shadow raster is interpreted as SOLWEIG-style `0=shade` and `1=sun`
when the value distribution supports that convention. Shade fraction is the
fraction of route samples with shadow value `<= 0.5`.

## Heat Dose Definition

Heat dose is the mean positive excess above the comfort threshold:

```text
heat_dose = mean(max(0, UTCI - comfort_threshold_c))
```

## Feature Vector Definition

The edge feature vector includes length, travel time, mean UTCI, max UTCI, heat
dose, shade fraction, scenic score, noise score, slope, elevation change, POI
density, and uncertainty.

## Preference / Cost Function

Preference weights map the feature vector to a scalar disutility. Scenicness is
modeled as `1 - scenic_score`; quietness uses traffic/noise score; coolness uses
UTCI, heat dose, and sunlit fraction.

## Detour-Constrained Route Search

The proposed route is found by label-setting search over accumulated scalar cost
and accumulated distance, enforcing:

```text
route_distance <= (1 + detour_ratio) * shortest_path_distance
```

## OD Sampling

OD pairs are sampled from graph nodes inside valid raster coverage. Candidate
pairs are retained only when their network shortest-path distance lies inside
the configured range.

## Baseline Definitions

- `shortest_distance`: length-only shortest path.
- `azimuth_heuristic`: solar azimuth/altitude shade fallback without direct-shadow raster.
- `shadow_only`: route search on direct-shadow-derived shade fraction.
- `mean_utci`: route search emphasizing mean modeled UTCI.
- `max_utci`: route search emphasizing peak modeled UTCI.
- `heat_dose`: route search emphasizing threshold exceedance.
- `weighted_sum`: unconstrained scalar weighted route.
- `proposed_full`: full radiative-perceptual feature vector with hard detour constraint.
