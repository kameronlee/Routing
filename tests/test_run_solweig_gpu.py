from scripts.run_solweig_gpu import filter_metfile_to_hour, parse_metfile_hours


def test_filter_metfile_to_hour(tmp_path) -> None:
    source = tmp_path / "met.txt"
    source.write_text(
        "\n".join(
            [
                "iy id it imin Q* QH QE Qs Qf Wind RH Td press rain Kdn snow ldown fcld wuh xsmd lai_hr Kdiff Kdir Wd",
                "2026 182 8 0 -999 -999 -999 -999 -999 1 50 25 101 0 400 -999 -999 -999 -999 -999 -999 -999 -999 180",
                "2026 182 14 0 -999 -999 -999 -999 -999 2 60 32 101 0 800 -999 -999 -999 -999 -999 -999 -999 -999 210",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    destination = tmp_path / "hour.txt"

    filter_metfile_to_hour(source, destination, 14)

    assert parse_metfile_hours(destination) == [14]


def test_parse_metfile_hours(tmp_path) -> None:
    source = tmp_path / "met.txt"
    source.write_text(
        "iy id it imin Q* QH QE Qs Qf Wind RH Td press rain Kdn snow ldown fcld wuh xsmd lai_hr Kdiff Kdir Wd\n"
        "2026 182 16 0 -999 -999 -999 -999 -999 2 60 32 101 0 800 -999 -999 -999 -999 -999 -999 -999 -999 210\n",
        encoding="utf-8",
    )

    assert parse_metfile_hours(source) == [16]
