# Archived pilot and reanalysis

`raw/` preserves the original OD pairs and compressed route/tuning records.
`provenance.json` gives SHA-256 hashes of the uncompressed CSV bytes. These are
historical outputs, not results from the corrected router.

`analysis/` contains the common-set tables, OD-cluster intervals, tuning
comparison, runtime summaries, and audit checks. Regenerate them from the repo
root with:

```bash
python experiments/reanalyze_geohealth3466.py --figures
```

The main run has 10,000 attempts and the tuning run 800. Their common accepted
sets differ: 1,386 records per main method and 142 per tuning variant. The
historical `heat_dose` column stores mean positive UTCI exceedance, not a
cumulative dose. Its temperature-difference unit is K.

The figures show the endpoint sample, a recorded shortest/UTCI route comparison
beside all 309 matched outcomes at a 20% allowance, and runtime ECDFs including
failed attempts. The mapped example is nearest the median paired reduction.
`analysis/route_tradeoff.csv` contains every point in the paired plot.
Frozen geometries and GIS source attribution are
in [figure_inputs/](figure_inputs/). Background layers are display context;
they do not recover the historical graph, UTCI, or shadow field.
