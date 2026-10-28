"""Redraw serialized OD endpoints in metric coordinates, without inventing OD data."""
import argparse
import csv
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--od-pairs", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from rasterio.warp import transform

    with Path(args.od_pairs).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("No OD records supplied")
    origins = [(float(row["origin_lon"]), float(row["origin_lat"])) for row in rows]
    destinations = [(float(row["destination_lon"]), float(row["destination_lat"])) for row in rows]
    ox, oy = transform("EPSG:4326", "EPSG:32618", *zip(*origins))
    dx, dy = transform("EPSG:4326", "EPSG:32618", *zip(*destinations))
    plt.rcParams.update({"font.size": 9, "pdf.fonttype": 42, "ps.fonttype": 42})
    fig, ax = plt.subplots(figsize=(4.2, 4.4), layout="constrained")
    for x1,y1,x2,y2 in zip(ox,oy,dx,dy):
        ax.plot([x1/1000,x2/1000], [y1/1000,y2/1000], color="0.6", alpha=.10, linewidth=.4)
    ax.scatter([v/1000 for v in ox], [v/1000 for v in oy], s=4, label="Origin")
    ax.scatter([v/1000 for v in dx], [v/1000 for v in dy], s=4, label="Destination")
    ax.set(xlabel="Easting (km, UTM 18N)", ylabel="Northing (km, UTM 18N)", aspect="equal")
    ax.legend(fontsize=9)
    fig.suptitle(f"{len(rows)} OD pairs; EPSG:32618", fontsize=10)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    plt.close(fig)


if __name__ == "__main__":
    main()
