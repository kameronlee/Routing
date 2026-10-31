# Primary 5 m experiment

The frozen records contain 10,000 routing attempts on the original 500 OD
pairs, 10,000 rescored 20 m paths, and 1,600 sensitivity attempts. All return
successful records. The 20 m and 5 m runs use the same input bytes and routing
code; the original shortest paths have identical 5 m scores.

Mean exceedance falls by 0.91–0.94 K with 4.59–6.34% extra distance. Moving
from 20 m to 5 m changes 70–76% of environmental paths. On the common 5 m
field, mean exceedance is 0.06–0.10 K lower for the newly selected routes.
These comparisons concern one modeled hour and have no independent field
validation.

`raw/provenance.json` checksums the records. Manifests retain per-shard source
hashes and configurations. `executed_source.tar.gz` preserves the exact code
and dependency declarations used for execution. One historical source file
uses different line endings; the analysis verifies its original bytes and
confirms identical code after LF normalization.

`analysis/` contains the paired tables, two figures, and audit checks. Use the
[experiment commands](../../../experiments/README.md) to rebuild them.
