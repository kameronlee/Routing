"""Small IO helpers for experiment scripts."""

from __future__ import annotations

import csv
from datetime import datetime, UTC
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from routing_backend.experiment_config import ExperimentConfig
from routing_backend.raster_data import project_root


def ensure_output_layout(config: ExperimentConfig) -> None:
    """Create standard experiment output directories."""

    for path in [
        config.output_dir,
        config.output_dir / "figures",
        config.output_dir / "tables",
        config.output_dir / "audit",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def write_json(path: str | Path, payload: Any) -> None:
    """Write formatted JSON."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_markdown(path: str | Path, text: str) -> None:
    """Write a Markdown report."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text.rstrip() + "\n", encoding="utf-8")


def write_csv(path: str | Path, rows: Iterable[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    """Write dictionaries to CSV, preserving explicit field order when given."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    row_list = list(rows)
    if fieldnames is None:
        fieldnames = []
        for row in row_list:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in row_list:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def read_csv(path: str | Path) -> list[dict[str, str]]:
    """Read a CSV file into a list of dictionaries."""

    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def config_hash(config: ExperimentConfig) -> str:
    """Return a stable short hash for a config snapshot."""

    payload = json.dumps(config.to_dict(), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def make_run_id(config: ExperimentConfig) -> str:
    """Return a readable run id that can be stored in output rows."""

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{config.study_name}-{stamp}-{config_hash(config)}"


def repo_relative(path: str | Path) -> str:
    """Return a path relative to the repository root when possible."""

    path_obj = Path(path).resolve()
    try:
        return str(path_obj.relative_to(project_root()))
    except ValueError:
        return str(path_obj)


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True)
    return value
