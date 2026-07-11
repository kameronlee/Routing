#!/usr/bin/env python
"""Generate reproducible OD pairs inside graph and raster coverage."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from routing_backend.experiment_config import load_experiment_config
from routing_backend.experiment_io import ensure_output_layout, write_csv, write_markdown
from routing_backend.od_sampling import OD_PAIR_COLUMNS, generate_od_pairs, load_graph_for_sampling


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--pair-count", "--count", dest="pair_count", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--min-shortest-distance-m", type=float)
    parser.add_argument("--max-shortest-distance-m", type=float)
    args = parser.parse_args()

    config = load_experiment_config(args.config)
    config.require_existing_inputs()
    ensure_output_layout(config)
    graph = load_graph_for_sampling(config.graph_path)
    pair_count = args.pair_count or config.od_pair_count
    seed = args.seed if args.seed is not None else config.random_seed
    min_distance = args.min_shortest_distance_m or config.min_shortest_distance_m
    max_distance = args.max_shortest_distance_m or config.max_shortest_distance_m
    pairs = generate_od_pairs(
        graph,
        [config.utci_raster_path, config.shadow_raster_path],
        pair_count=pair_count,
        seed=seed,
        min_distance_m=min_distance,
        max_distance_m=max_distance,
    )
    rows = [pair.to_row() for pair in pairs]
    write_csv(config.output_dir / "od_pairs.csv", rows, OD_PAIR_COLUMNS)
    write_markdown(
        config.output_dir / "od_sampling_report.md",
        f"""# OD Sampling Report: {config.study_name}

- Requested pairs: {pair_count}
- Generated pairs: {len(pairs)}
- Random seed: {seed}
- Minimum shortest-path distance (m): {min_distance}
- Maximum shortest-path distance (m): {max_distance}
- Graph path: `{config.graph_path}`
- Raster coverage filters: `{config.utci_raster_path}`, `{config.shadow_raster_path}`

Pairs are sampled from the real configured walking graph and filtered by real raster coverage. Synthetic graphs are not used.
""",
    )
    _maybe_write_pair_map(config, rows)


def _maybe_write_pair_map(config, rows: list[dict]) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(7, 7), constrained_layout=True)
    for row in rows[:500]:
        ax.plot(
            [float(row["origin_lon"]), float(row["destination_lon"])],
            [float(row["origin_lat"]), float(row["destination_lat"])],
            color="0.6",
            linewidth=0.4,
            alpha=0.25,
        )
    ax.scatter([float(row["origin_lon"]) for row in rows], [float(row["origin_lat"]) for row in rows], s=4, label="origin")
    ax.scatter(
        [float(row["destination_lon"]) for row in rows],
        [float(row["destination_lat"]) for row in rows],
        s=4,
        label="destination",
    )
    ax.set_title("Sampled OD pairs")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.legend()
    fig.savefig(config.output_dir / "figures" / "od_pairs_map.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
