# Corrected DC run

`raw/` contains 10,000 routing attempts and 1,600 one-factor sensitivity
attempts. All succeed; all sensitivity paths also have 5 m rescoring.
The same 500 OD pairs occur at four budgets for every main-run method.

`analysis/` contains audited tables and vector figures. Rebuild them with:

```bash
python experiments/analyze_corrected_validation.py
python experiments/make_corrected_figures.py
```

`raw/provenance.json` checksums the frozen files. Main manifests retain their
original configuration/run identifiers. Matching stays within each shard.
`inputs.json` pins the raster/graph bytes; `building_height_derivation.json`
records DSM minus DEM. `executed_source.tar.gz` preserves the exact source
bytes, including line endings, used for the recorded hashes.

The map example is nearest the median paired reduction at 20% allowance,
with OD ID breaking ties. Separately attributed DC GIS roads and water are
display context and do not enter routing or exposure calculations.
