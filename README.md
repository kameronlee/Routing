# Heat-aware pedestrian routing

This is the code for my GeoHealth 2026 pilot on walking routes in Washington,
DC. It samples modeled UTCI and shade along a street network, then searches
for routes within a chosen distance allowance.

The study covers 500 OD pairs and one modeled hour. On the common successful
subset, environmental routes reduce mean UTCI exceedance by 0.576–0.701 K and
add 8.32–9.30% distance. These are modeled outcomes, not measured comfort or
health benefits. About a quarter of environmental attempts fail.

## Start

Use Python 3.10 or newer in a virtual environment:

```bash
python -m pip install -e ".[dev,experiments]"
python -m pytest
```

Real routing needs the graph and raster inputs named in `configs/`. Git LFS
pointers alone are not enough. See [setup](docs/setup.md) for data preparation,
the API, and the demo app.

## Paper and results

- [Paper source and PDF](paper/geohealth3466/)
- [Original OD pairs and route records](paper_assets/review3466/raw/)
- [Reanalysis tables](paper_assets/review3466/analysis/)
- [Revision notes and remaining work](paper/REVIEW_3466.md)

Recompute the archived results without loading the large raster inputs:

```bash
python experiments/reanalyze_geohealth3466.py --figures
```

The revision fixes budget handling, shortest-route fallback, and sampled
exceedance. The paper reanalyzes the original run; the corrected router still
needs a full real-data rerun. Threshold and sampling convergence are also
untested.

The repository includes the earlier ClearHelp notice-reading prototype under
`ClearHelp/`. It is separate from the paper experiment.
