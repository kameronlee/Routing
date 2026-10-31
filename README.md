# Heat-aware pedestrian routing

Code and data for my GeoHealth 2026 pilot in Washington, DC. The experiment
compares four environmental objectives with shortest distance on 500 OD pairs
at one modeled hour.

The corrected run returns all 10,000 routes within their distance budgets.
Mean UTCI exceedance falls by 0.92–0.96 K, with 4.84–6.55% extra distance.
Some requests use shortest-path fallback. Sampling changes many selected
paths, and the search cap can miss better solutions. I haven't validated the
thermal field or measured comfort or health outcomes.

## Start

Use Python 3.10 or newer in a virtual environment:

```bash
python -m pip install -e ".[dev,experiments]"
python -m pytest
```

Rebuild the published tables and figures from the frozen records:

```bash
python experiments/analyze_corrected_validation.py
python experiments/make_corrected_figures.py
```

## Paper and data

- [Paper (PDF)](paper/geohealth3466/main.pdf)
- [Corrected records, checksums, and analysis](paper_assets/review3466/corrected/)
- [Original OD pairs and historical records](paper_assets/review3466/raw/)
- [Exact-reference checks](paper_assets/review3466/solver_validation/)
- [Rerun instructions](experiments/README.md) and [reviewer response](paper/REVIEW_3466.md)

Real routing needs the versioned graph and rasters, downloaded through Git
LFS. Building heights must be derived by subtracting terrain elevation from
the building DSM. See [setup](docs/setup.md) for the API and demo app.

The older ClearHelp prototype under `ClearHelp/` is separate from this study.
