#!/usr/bin/env python
"""Draw corrected-run routes, geographic context, source counts, and all runtimes."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
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
        for direction in ("Nw", "Ne", "Sw", "Se"):
            label = label.replace(direction, direction.upper())
        labels.append((name, label, .5, (0, 7)))
        points.append(point)
        if len(labels) == 3:
            break
    return labels


def diagnostics(routes, out):
    fig = plt.figure(figsize=(7, 3.55))
    bars = fig.add_axes([.17, .34, .29, .43])
    categories = [("cost_shortest", "Cost path", "#4F7771"),
                  ("label_search", "Label search", "#A7B8B5"),
                  ("shortest_fallback", "Fallback", "#D3D3D3"),
                  ("rejected", "Rejected", "#7B4A48")]
    left = np.zeros(4)
    used = []
    for source, name, color in categories:
        counts = np.array([sum(r["method"] == method and
            (r["route_source"] == source if source != "rejected" else r["success"] != "true")
            for r in routes) for method in METHODS[1:]])
        if counts.sum():
            bars.barh(range(4), counts, left=left, height=.58, color=color, edgecolor="white", linewidth=.6)
            used.append(Patch(facecolor=color, label=name))
        left += counts
    assert np.all(left == 2000)
    bars.set(yticks=range(4), yticklabels=NAMES[1:], xlim=(0, 2000), xticks=[0, 1000, 2000], xlabel="Attempts")
    bars.invert_yaxis()
    bars.spines[["top", "right", "left"]].set_visible(False)
    bars.tick_params(axis="y", length=0, pad=4)
    bars.legend(handles=used, loc="upper center", bbox_to_anchor=(.5, 1.38), ncol=2,
                frameon=False, fontsize=8, handlelength=1.2, columnspacing=1.0)
    ecdf = fig.add_axes([.62, .34, .355, .49])
    all_times = [float(r["runtime_ms"]) / 1000 for r in routes]
    assert all(np.isfinite(t) and t > 0 for t in all_times)
    xmin = 10 ** np.floor(np.log10(min(all_times)))
    xmax = 10 ** np.ceil(np.log10(max(all_times)))
    for method, name, color, style in zip(METHODS, NAMES, COLORS, LINESTYLES):
        values = np.sort([float(r["runtime_ms"]) / 1000 for r in routes if r["method"] == method])
        ecdf.step(np.r_[xmin, values, xmax], np.r_[0, np.arange(1, len(values) + 1) / len(values), 1],
                  where="post", color=color, ls=style, lw=1.15, label=name)
    ecdf.set(xscale="log", xlim=(xmin, xmax), ylim=(0, 1.02), yticks=[0, .5, 1],
             xlabel="End-to-end runtime (s)", ylabel="Cumulative proportion")
    ecdf.spines[["top", "right"]].set_visible(False)
    ecdf.grid(axis="y", lw=.45, color="#DDDDDD")
    handles = [Line2D([0], [0], color=color, ls=style, lw=1.2, label=name)
               for name, color, style in zip(NAMES, COLORS, LINESTYLES)]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.5, .005),
               ncol=3, frameon=False, fontsize=8.5, columnspacing=1.2, handlelength=2.0)
    fig.text(.02, .96, "(a) Route sources", fontsize=10)
    fig.text(.62, .96, "(b) All attempts", fontsize=10)
    save_figure(fig, out / "runtime_ecdf.pdf")


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
    diagnostics(routes, out)
    audit = {"cases": cases, "street_labels": labels, "map_extent_m": extents, "map_crs": "EPSG:32618",
             "context_scope": "Frozen DC GIS display layers; excluded from routing and exposure calculation",
             "routes_sha256": hashlib.sha256((args.raw / "routes_summary.csv.gz").read_bytes()).hexdigest(),
             "all_runtime_observations": len(routes), "matplotlib": matplotlib.__version__, "numpy": np.__version__}
    (out / "figure_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
