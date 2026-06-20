# Demo Data Notes

The files in `data/processed` are intentionally small, cached artifacts for the hackathon MVP.

- `graph.json`: walkable graph with edge-level heat, shade, slope, vegetation, and tract metadata.
- `heat_surface.geojson`: point-based heat features used by the frontend heat layer.
- `vulnerability.geojson`: tract polygons for Washington D.C.
- `locations.json`: known demo destinations used by the frontend search UI.
- `telemetry_replay.jsonl`: replay-safe telemetry stream matching the MQTT schema.

Replace these files with real exports from OSM, municipal GIS portals, and preprocessing scripts when moving beyond the demo dataset.
