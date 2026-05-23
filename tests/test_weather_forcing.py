from scripts.build_weather_forcing import write_solweig_table


def test_write_solweig_table_uses_umep_columns(tmp_path) -> None:
    payload = {
        "hourly": {
            "time": ["2026-07-01T14:00"],
            "temperature_2m": [31.5],
            "relative_humidity_2m": [62],
            "surface_pressure": [1012.0],
            "wind_speed_10m": [2.4],
            "wind_direction_10m": [210],
            "shortwave_radiation": [810.0],
            "direct_radiation": [620.0],
            "diffuse_radiation": [190.0],
        }
    }
    path = tmp_path / "met.txt"

    write_solweig_table(path, payload)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].split() == [
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
    values = lines[1].split()
    assert values[:4] == ["2026", "182", "14", "0"]
    assert values[9] == "2.40000"
    assert values[11] == "31.50"
    assert values[12] == "101.20"
    assert values[14] == "810.00"
