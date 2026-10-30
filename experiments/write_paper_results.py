#!/usr/bin/env python
"""Write the paper's numerical macros and tables from audited result files."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
from statistics import fmean

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "paper_assets/review3466/corrected"
METHODS = ["shortest_distance", "azimuth_heuristic", "shadow_only", "heat_dose", "proposed_full"]
NAMES = ["Shortest", "Hybrid azimuth", "Direct shadow", "UTCI exceedance", "Composite"]


def read_csv(path):
    with (gzip.open(path, "rt", newline="") if path.suffix == ".gz" else path.open(newline="")) as stream:
        return list(csv.DictReader(stream))


def number(value, digits=3):
    value = float(value)
    if abs(value) < .5 * 10 ** -digits:
        value = 0.0
    return f"{value:.{digits}f}"


def interval(low, high):
    return rf"[${number(low)}$, ${number(high)}$]"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=ASSETS)
    parser.add_argument("--paper", type=Path, default=ROOT / "paper/geohealth3466")
    parser.add_argument("--artifact-commit", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.artifact_commit):
        parser.error("artifact-commit must be a full immutable Git commit")
    analysis, raw = args.assets / "analysis", args.assets / "raw"
    outcomes = read_csv(analysis / "matched_outcomes.csv")
    all_outcomes = {r["method"]: r for r in outcomes if r["budget"] == "all"}
    by_budget = {(r["method"], r["budget"]): r for r in outcomes}
    contrasts = {(r["method_a"], r["method_b"]): r for r in read_csv(analysis / "paired_heat_contrasts.csv") if r["detour_ratio"] == "all"}
    sensitivity = {r["method"]: r for r in read_csv(analysis / "sensitivity_outcomes.csv")}
    audit = json.loads((analysis / "audit.json").read_text())
    figure = json.loads((analysis / "figure_audit.json").read_text())
    routes = read_csv(raw / "routes_summary.csv.gz")
    runtimes = read_csv(analysis / "runtime_summary.csv")
    sources = read_csv(analysis / "route_sources.csv")
    example = figure["cases"][0]
    example_route = next(r for r in routes if r["pair_id"] == example["pair_id"] and
                         float(r["detour_ratio"]) == .2 and r["method"] == "heat_dose")
    values = {}

    def put(key, value):
        text = str(value)
        values[key] = "$" + text + "$" if re.fullmatch(r"-\d+(?:\.\d+)?", text) else text

    def span(key, numbers, digits):
        numbers = list(map(float, numbers))
        put(key, f"{number(min(numbers), digits)}--{number(max(numbers), digits)}")

    put("ArtifactCommit", args.artifact_commit)
    put("CommonCases", f"{audit['common_pair_budget_cases']:,}")
    put("CommonPairs", audit["common_od_pairs"])
    put("AcceptedCount", f"{audit['successes']:,}")
    span("HeatRange", [all_outcomes[m]["mean_delta_H_K"] for m in METHODS[1:]], 2)
    span("DistanceRange", [all_outcomes[m]["mean_extra_percent"] for m in METHODS[1:]], 2)
    put("BaselineH", number(fmean(float(r["heat_dose"]) for r in routes if r["method"] == "shortest_distance" and r["success"] == "true")))
    for method, label in (("heat_dose", "Heat"), ("shadow_only", "Shadow"), ("proposed_full", "Composite")):
        reversal = int(all_outcomes[method]["lower_H_higher_J"])
        put(f"{label}ReversalCount", f"{reversal:,}")
        put(f"{label}ReversalPct", number(100 * reversal / audit["common_pair_budget_cases"], 1))
    fallback = [sum(int(r["count"]) for r in sources if r["method"] == m and r["route_source"] == "shortest_fallback") / 20 for m in METHODS[1:]]
    span("FallbackRange", fallback, 2)
    heat_composite = contrasts[("heat_dose", "proposed_full")]
    heat_shadow = contrasts[("shadow_only", "heat_dose")]
    for label, value, low, high, other in (
        ("Composite", float(heat_composite["mean_H_b_minus_H_a_K"]), float(heat_composite["ci95_low_K"]), float(heat_composite["ci95_high_K"]), "composite"),
        ("Shadow", -float(heat_shadow["mean_H_b_minus_H_a_K"]), -float(heat_shadow["ci95_high_K"]), -float(heat_shadow["ci95_low_K"]), "direct-shadow setting")):
        put(f"Heat{label}Winner", "UTCI-focused setting" if value >= 0 else other)
        put(f"Heat{label}Loser", other if value >= 0 else "UTCI-focused setting")
        put(f"Heat{label}Contrast", number(abs(value)))
        put(f"Heat{label}CI", interval(low, high) if value >= 0 else interval(-high, -low))
        put(f"Heat{label}IntervalNote", "The interval includes zero." if low <= 0 <= high else "")
    put("BudgetTwentyCases", example["common_records_at_budget"])
    put("ExamplePair", r"\texttt{" + example["pair_id"].replace("_", r"\_") + "}")
    put("ExampleExtra", number(100 * float(example_route["excess_distance_ratio"]), 1))
    put("ExampleReduction", number(example["delta_H_K"], 2))
    put("HigherHAtTwenty", by_budget[("heat_dose", "0.2")]["higher_H"])
    higher = int(by_budget[("heat_dose", "0.2")]["higher_H"])
    put("HeatWorseningSentence", "None has higher $H$ than its matched shortest route." if higher == 0 else
        f"Across these pairs, {higher} returned UTCI routes have higher $H$ than shortest distance.")
    for budget, label in (("0.05", "Low"), ("0.3", "High")):
        selected = by_budget[("proposed_full", budget)]
        put(f"Composite{label}H", number(selected["mean_delta_H_K"]))
        put(f"Composite{label}Extra", number(selected["mean_extra_percent"], 2))
    put("SensitivityAccepted", f"{audit['sensitivity_successes']:,}")
    put("DenseAccepted", f"{audit['dense_check_successes']:,}")
    put("SensitivityPairs", audit["sensitivity_common_pairs"])
    weight_rows = [r for name, r in sensitivity.items() if name.startswith("weight_")]
    span("WeightChangeRange", [r["path_changes"] for r in weight_rows], 0)
    for threshold, label in ((24, "Low"), (28, "High")):
        row = sensitivity[f"threshold_{threshold}C"]
        put(f"Threshold{label}Changed", row["path_changes"])
        put(f"Threshold{label}Delta", number(row["mean_reference_H_minus_variant_H_5m_K"]))
        change = float(row["mean_reference_H_minus_variant_H_5m_K"])
        put(f"Threshold{label}Magnitude", number(abs(change)))
        put(f"Threshold{label}Direction", "lower" if change >= 0 else "higher")
    put("SamplingFiveChanges", sensitivity["sampling_5m"]["path_changes"])
    put("SpacingMedian", number(sensitivity["reference"]["median_abs_spacing_error_K"]))
    put("SpacingPninety", number(sensitivity["reference"]["p90_abs_spacing_error_K"]))
    put("ControlChanges", audit["reference_control_path_changes"])
    span("RuntimeMedianRange", [r["median_s"] for r in runtimes], 3)
    span("RuntimePninetyRange", [r["p90_s"] for r in runtimes], 3)
    put("RuntimeMaximum", number(max(float(r["max_s"]) for r in runtimes)))

    main_lines = []
    for method, name in zip(METHODS, NAMES):
        row = all_outcomes[method]
        if method == "shortest_distance":
            heat = "$0.000$"
        else:
            comparison = contrasts[("shortest_distance", method)]
            heat = "$" + number(row["mean_delta_H_K"]) + "$ " + interval(-float(comparison["ci95_high_K"]), -float(comparison["ci95_low_K"]))
        shade = "---" if method == "azimuth_heuristic" else "$" + number(row["mean_delta_S"]) + "$"
        main_lines.append(name + " & " + heat + " & $" + number(float(row["mean_delta_J_K_m"]) / 1000) + "$ & " + shade + " & $" + number(row["mean_extra_percent"], 2) + r"$\\")
    main_table = r"""\begin{table*}[t]
\caption{Matched outcomes on the same \CommonCases{} OD--budget cases. Positive $\Delta H$ and $\Delta J$ favor the environmental route; $\Delta S$ is added shade. Intervals resample whole OD pairs. Hybrid shade uses a different surrogate, so its comparison is omitted. Fallbacks are included.}
\label{tab:common}\centering\small
\begin{tabular}{@{}lrrrr@{}}\toprule
Method & Mean $\Delta H$ (K) [95\% interval] & Mean $\Delta J$ (K\,km) & Mean $\Delta S$ & Extra distance (\%)\\\midrule
""" + "\n".join(main_lines) + r"""
\bottomrule\end{tabular}
\end{table*}"""
    weight_lines = []
    for field, label in (("cool", "Thermal"), ("shade", "Shade"), ("scenic", "Scenic"), ("quiet", "Traffic"), ("slope", "Slope")):
        zero, twice = sensitivity[f"weight_{field}_x0"], sensitivity[f"weight_{field}_x2"]
        weight_lines.append(f"{label} & {zero['path_changes']}/{twice['path_changes']} & $" + number(zero["mean_reference_H_minus_variant_H_5m_K"]) + "/" + number(twice["mean_reference_H_minus_variant_H_5m_K"]) + r"$\\")
    weight_table = r"""\begin{table}[t]
\caption{One-factor composite sensitivity on \SensitivityPairs{} complete paired paths, scored at 5 m and $26^\circ$C. Entries show removed/doubled coefficients. Positive $\Delta H$ means lower exceedance than the default.}
\label{tab:sensitivity}\centering\small
\begin{tabular}{@{}lrr@{}}\toprule
Coefficient & Changed paths & $\Delta H$ (K)\\\midrule
""" + "\n".join(weight_lines) + r"""
\bottomrule\end{tabular}
\end{table}"""
    sampling_lines = []
    for spacing, method in ((5, "sampling_5m"), (10, "sampling_10m"), (20, "reference"), (40, "sampling_40m")):
        row = sensitivity[method]
        sampling_lines.append(f"{spacing} & " + number(row["median_abs_spacing_error_K"]) + " & " + number(row["p90_abs_spacing_error_K"]) + " & " + row["path_changes"] + r"\\")
    sampling_table = r"""\begin{table}[t]
\caption{Sampling disagreement with 5 m scoring of each same path, on \SensitivityPairs{} complete cases. Changes compare edge sequences with the 20 m default. The 5 m error is zero by construction.}
\label{tab:sampling}\centering\small
\begin{tabular}{@{}rrrr@{}}\toprule
Spacing (m) & Median error (K) & 90th pct. (K) & Changed\\\midrule
""" + "\n".join(sampling_lines) + r"""
\bottomrule\end{tabular}
\end{table}"""
    definitions = [r"% Generated by experiments/write_paper_results.py; do not hand-edit numerical results."]
    definitions += ["\\newcommand{\\" + name + "}{" + value + "}" for name, value in values.items()]
    definitions += [r"\newcommand{\MainResultsTable}{" + main_table + "}",
                    r"\newcommand{\WeightResultsTable}{" + weight_table + "}",
                    r"\newcommand{\SamplingResultsTable}{" + sampling_table + "}"]
    args.paper.mkdir(parents=True, exist_ok=True)
    (args.paper / "results.tex").write_text("\n".join(definitions) + "\n", encoding="utf-8")
    (args.paper / "results_generation.json").write_text(json.dumps({
        "artifact_commit": args.artifact_commit, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(analysis.glob("*.csv"))},
        "macros": values}, indent=2) + "\n")
    print(f"Wrote {len(values)} numerical macros and three tables")


if __name__ == "__main__":
    main()
