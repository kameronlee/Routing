#!/usr/bin/env python
"""Draw the sample geography and recorded route comparison used in the paper."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import shape, box
from shapely.ops import unary_union

from make_geohealth_figures import (
    ROOT, METHODS, NAMES, COLORS, LINESTYLES, geographic_context, selected_cases,
    freeze_cases, route_comparison, study_area, save_figure, geometry_parts, load_json,
)


def read_rows(path):
    with (gzip.open(path, "rt", newline="") if path.suffix == ".gz" else path.open(newline="")) as stream:
        return list(csv.DictReader(stream))


def street_labels(case_dir, context):
    paths = unary_union([shape(f["geometry"]) for f in load_json(case_dir / "route_cases.geojson.gz")["features"]])
    # Select nearby named roads by their length within 20 m of the two paths.
    groups = {}
    for geometry, name in context[0]:
        if name and geometry.distance(paths) < 20:
            groups.setdefault(name, []).append(geometry)
    ranked = []
    for name, geometries in groups.items():
        merged = unary_union(geometries)
        near = merged.intersection(paths.buffer(20))
        if near.length > 150:
            point = near.centroid
            ranked.append((near.length, name, point))
    labels, points = [], []
    for _, name, point in sorted(ranked, key=lambda x: (-x[0], x[1])):
        if any(point.distance(previous) < 250 for previous in points):
            continue
        label = name.title()
        label = re.sub(r"(\d+)(St|Nd|Rd|Th)\b", lambda m: m[1] + m[2].lower(), label)
        for direction in ("Nw", "Ne", "Sw", "Se"):
            label = label.replace(direction, direction.upper())
        labels.append((name, label, .5, (0, 7)))
        points.append(point)
        if len(labels) == 3:
            break
    return labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "paper_assets/review3466/corrected/raw")
    parser.add_argument("--output", type=Path, default=ROOT / "paper_assets/review3466/corrected/analysis")
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    routes = read_rows(args.raw / "routes_summary.csv.gz")
    od = read_rows(ROOT / "paper_assets/review3466/raw/od_pairs.csv")
    plt.rcParams.update({"font.family": "STIXGeneral", "mathtext.fontset": "stix", "font.size": 9,
                         "axes.labelsize": 9, "xtick.labelsize": 8, "ytick.labelsize": 8,
                         "pdf.fonttype": 42, "ps.fonttype": 42, "axes.linewidth": .6})
    cases = selected_cases(routes)
    case_dir = args.raw.parent / "figure_inputs"
    freeze_cases(args.raw / "selected_routes.geojson", cases, case_dir=case_dir,
                 source_label="Corrected run: selected_routes.geojson; full shard hashes in manifests")
    context = geographic_context()
    labels = street_labels(case_dir, context)
    extents = route_comparison(cases, routes, context, out, case_dir=case_dir,
                              street_labels=labels, auto_extent=True)
    study_area(od, context, extents, out)
    audit = {"cases": cases, "street_labels": labels, "map_extent_m": extents, "map_crs": "EPSG:32618",
             "context_scope": "Frozen DC GIS display layers; excluded from routing and exposure calculation",
             "routes_sha256": hashlib.sha256((args.raw / "routes_summary.csv.gz").read_bytes()).hexdigest(),
             "all_runtime_observations": len(routes), "matplotlib": matplotlib.__version__, "numpy": np.__version__}
    (out / "figure_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
