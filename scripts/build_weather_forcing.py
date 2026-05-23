"""Download real hourly meteorological/solar forcing for Washington, D.C.

The default source is Open-Meteo's archive/forecast API, which does not require
an API key. The output includes a raw CSV plus a UMEP/SOLWEIG metfile that can
be passed to SOLWEIG-GPU with ``use_own_met=True``.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
import json
from pathlib import Path
from urllib.parse import urlencode

import requests

USER_AGENT = "RoutingWeatherForcing/0.1"
DC_LAT = 38.9072
DC_LON = -77.0369
HOURLY_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
]


def endpoint_for_range(start: date, end: date) -> str:
    """Choose archive for past dates and forecast for current/future dates."""

    today = date.today()
    if end < today:
        return "https://archive-api.open-meteo.com/v1/archive"
    return "https://api.open-meteo.com/v1/forecast"


def download_open_meteo(start: date, end: date) -> dict:
    """Fetch hourly DC weather/solar data from Open-Meteo."""

    params = {
        "latitude": DC_LAT,
        "longitude": DC_LON,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(HOURLY_FIELDS),
        "timezone": "America/New_York",
        "wind_speed_unit": "ms",
    }
    url = f"{endpoint_for_range(start, end)}?{urlencode(params)}"
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
    response.raise_for_status()
    payload = response.json()
    payload["_source_url"] = url
    return payload


def write_hourly_csv(path: Path, payload: dict) -> None:
    """Write hourly data to CSV."""

    hourly = payload["hourly"]
    times = hourly["time"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", *HOURLY_FIELDS])
        for idx, timestamp in enumerate(times):
            writer.writerow([timestamp, *[hourly.get(field, [None] * len(times))[idx] for field in HOURLY_FIELDS]])


def write_solweig_table(path: Path, payload: dict) -> None:
    """Write the UMEP/SOLWEIG custom meteorological text format.

    SOLWEIG-GPU reads the same 24-column metfile used by UMEP. The column named
    ``Td`` is consumed as air temperature by SOLWEIG-GPU, so it is populated
    with Open-Meteo ``temperature_2m`` in degrees C.
    """

    hourly = payload["hourly"]
    times = hourly["time"]
    columns = [
        "iy",
        "id",
        "it",
        "imin",
        "Q*",
        "QH",
        "QE",
        "Qs",
        "Qf",
        "Wind",
        "RH",
        "Td",
        "press",
        "rain",
        "Kdn",
        "snow",
        "ldown",
        "fcld",
        "wuh",
        "xsmd",
        "lai_hr",
        "Kdiff",
        "Kdir",
        "Wd",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(" ".join(columns) + "\n")
        for idx, timestamp in enumerate(times):
            dt = datetime.fromisoformat(timestamp)
            row = [
                dt.year,
                int(dt.strftime("%j")),
                dt.hour,
                dt.minute,
                -999.0,
                -999.0,
                -999.0,
                -999.0,
                -999.0,
                hourly["wind_speed_10m"][idx],
                hourly["relative_humidity_2m"][idx],
                hourly["temperature_2m"][idx],
                hourly["surface_pressure"][idx] / 10.0,
                0.0,
                hourly["shortwave_radiation"][idx],
                -999.0,
                -999.0,
                -999.0,
                -999.0,
                -999.0,
                -999.0,
                hourly["diffuse_radiation"][idx],
                hourly["direct_radiation"][idx],
                hourly["wind_direction_10m"][idx],
            ]
            handle.write(
                "{:d} {:d} {:d} {:d} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} "
                "{:.5f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} "
                "{:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f}\n".format(
                    int(row[0]),
                    int(row[1]),
                    int(row[2]),
                    int(row[3]),
                    *[float(value) for value in row[4:]],
                )
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--start-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    payload = download_open_meteo(args.start_date, args.end_date)
    root = args.root.resolve()
    raw_path = root / "data" / "raw" / "meteorology" / f"open_meteo_dc_{args.start_date}_{args.end_date}.json"
    csv_path = root / "data" / "raw" / "meteorology" / f"open_meteo_dc_{args.start_date}_{args.end_date}.csv"
    solweig_path = root / "data" / "processed" / "solweig_inputs" / f"met_forcing_{args.start_date}_{args.end_date}.txt"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_hourly_csv(csv_path, payload)
    write_solweig_table(solweig_path, payload)
    print(f"raw: {raw_path}")
    print(f"csv: {csv_path}")
    print(f"solweig: {solweig_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
