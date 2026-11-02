"""Check that distributed manifests omit local checkout prefixes."""

import json
from pathlib import PurePosixPath, PureWindowsPath

from experiments.export_validation_bundle import portable_metadata_bytes


def test_portable_metadata_preserves_parameters_hashes_and_line_endings():
    original = (
        b'{\r\n  "path": "/work/study/data/graph.graphml",\r\n'
        b'  "run_id": "run-7", "sha256": "abcd", "spacing_m": 5\r\n}\r\n'
    )
    result = portable_metadata_bytes(original, PurePosixPath("/work/study"))

    assert result == original.replace(b"/work/study/", b"")
    assert json.loads(result)["path"] == "data/graph.graphml"
    assert result.count(b"\r\n") == original.count(b"\r\n")


def test_portable_metadata_handles_json_escaped_windows_prefixes():
    original = json.dumps({"path": r"C:\research\study\record.json"}).encode()

    result = portable_metadata_bytes(original, PureWindowsPath(r"C:\research\study"))

    assert json.loads(result) == {"path": "record.json"}


def test_portable_metadata_preserves_paths_outside_repository():
    original = b'{"path": "/work/study-other/record.json", "tool": "/usr/bin/python"}'

    assert portable_metadata_bytes(original, PurePosixPath("/work/study")) == original
