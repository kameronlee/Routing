# Paper Outline

## Title Options

- Detour-Constrained Radiative Routing with Raster-Backed UTCI and Direct Shadow
- Modeled Heat-Exposure-Aware Pedestrian Routing Under Explicit Detour Budgets
- A Computational Benchmark for Microclimate-Aware Pedestrian Routing

## Abstract Skeleton

We present a time-dependent, raster-backed pedestrian routing engine that
combines modeled UTCI, direct-shadow rasters, and perceptual street features
under explicit maximum detour constraints. Using a single Washington, DC
snapshot, we evaluate modeled heat exposure reductions relative to shortest-path
and shade/UTCI baselines over reproducible origin-destination pairs. Results are
reported as computational exposure metrics, not field-validated human comfort.

## Introduction

Motivate heat exposure during pedestrian travel, the practical need for bounded
detours, and the gap between scalar comfort routing and explicit resource
constraints. State the contribution as a computational routing and evaluation
pipeline for one controlled microclimate snapshot.

## Related Work Categories

- Thermal comfort and urban microclimate modeling
- Pedestrian routing and multi-objective shortest paths
- Shade-aware and heat-aware mobility systems
- Raster/vector fusion for spatial decision support
- Uncertainty and sensitivity analysis in urban climate tools

## Method

Describe graph construction, raster sampling, edge feature vectors, preference
weights, and detour-constrained label-setting search.

## Data

List GraphML walking graph, SOLWEIG/SOLWEIG-GPU UTCI raster, direct-shadow
raster, LiDAR-derived canopy/building/DEM rasters, land cover, and DDOT traffic
volume.

## Experiment Design

Use reproducible OD sampling inside graph and raster coverage, distance filters,
detour ratios, and method comparisons. Emphasize single-timestamp snapshot
evaluation.

## Baselines

Shortest distance, azimuth heuristic, shadow only, mean UTCI, max UTCI, heat
dose, weighted sum, and proposed full constrained routing.

## Results

Report modeled heat-dose reduction, mean/maximum UTCI reduction, shade-fraction
increase, excess distance, runtime, and failures.

## Ablations

Compare full model against no shadow raster, azimuth only, no traffic/noise,
no scenic, no uncertainty penalty, mean UTCI only, heat dose only, and shade
only. Document non-separable ablations rather than fabricating them.

## Sensitivity Analysis

Perturb UTCI offset, comfort threshold, shadow noise, sampling spacing, and
preference weights. Report whether conclusions are robust or sensitive.

## Remote Plausibility Validation

Use exported GeoJSON/Markdown audit cases to inspect route geometry, raster
coverage, and disagreement cases remotely. State that this is not field
validation.

## Limitations

Summarize modeled-only evidence, single timestamp, raster/model uncertainty,
proxy scenic/noise features, and lack of DC field transects.

## Ethics / Environmental Justice

Discuss unequal shade and heat exposure, accessibility impacts of detours, and
the need to avoid presenting modeled route recommendations as medical advice or
universal comfort guarantees.

## Conclusion

Reiterate bounded-detour routing with raster-backed modeled heat exposure and
the path toward multi-timestamp and field-validated studies.
