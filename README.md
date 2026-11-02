# Heat-aware pedestrian routing

Code and data for my GeoHealth 2026 pilot in Washington, DC. The experiment
compares four environmental objectives with shortest distance on 500 OD pairs
at one modeled hour. The main run samples at 5 m; a complete 20 m run
is compared on the same 5 m reporting field.

The corrected run returns all 10,000 routes within their distance budgets.
Mean UTCI exceedance falls by 0.91–0.94 K, with 4.59–6.34% extra distance.
Some requests use shortest-path fallback. Sampling changes many selected
paths, and the search cap can miss better solutions. I haven't validated the
thermal field or measured comfort or health outcomes.

## Start

Use Python 3.11 or newer in a virtual environment:

```bash
python -m pip install -e ".[dev,experiments]"
python -m pytest
```

Rebuild the published tables and figures from the frozen records:

```bash
python experiments/analyze_sampling_validation.py
python experiments/make_corrected_figures.py --raw paper_assets/review3466/sampling5/raw --output paper_assets/review3466/sampling5/analysis
```

## Paper and data

- [Paper (PDF)](paper/geohealth3466/main.pdf)
- [Corrected records, checksums, and analysis](paper_assets/review3466/sampling5/)
- [Original OD pairs and historical records](paper_assets/review3466/raw/)
- [Exact-reference checks](paper_assets/review3466/solver_validation/)
- [Rerun instructions](experiments/README.md) and [reviewer response](paper/REVIEW_3466.md)

Real routing needs the versioned graph and rasters, downloaded through Git
LFS. Building heights must be derived by subtracting terrain elevation from
the building DSM. [Experiment instructions](experiments/README.md) give the
input paths and commands.

## Citation

Use [CITATION.cff](CITATION.cff) when citing the code. Cite the accompanying
paper for the experiment and its results.
