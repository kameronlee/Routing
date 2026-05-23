"""Download and stage the Washington, D.C. routing data bundle.

The script keeps heavyweight LiDAR downloads explicit. By default it downloads
the official DC boundary, OSM extracts, DDOT traffic counts, DC land-cover and
tree-canopy sample tiles, the NOAA 2022 1 m DEM, LiDAR metadata/index files and
one raw COPC LAZ tile. Use ``--download-all-laz`` only when you are ready for a
multi-GB point-cloud download.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any
from urllib.parse import urlencode, urljoin

import requests

USER_AGENT = "RoutingDataBundle/0.1 (+https://github.com/kameronlee/Routing)"

BOUNDARY_QUERY = (
    "https://maps2.dcgis.dc.gov/dcgis/rest/services/"
    "DCGIS_DATA/Administrative_Other_Boundaries_WebMercator/MapServer/10/query"
)
TRAFFIC_VOLUME_QUERY = (
    "https://maps2.dcgis.dc.gov/dcgis/rest/services/"
    "DCGIS_DATA/Transportation_TrafficVolume_WebMercator/MapServer/4/query"
)
LAND_COVER_IMAGE = (
    "https://imagery.dcgis.dc.gov/dcgis/rest/services/"
    "UFD/Generalized_Land_Cover_2020/ImageServer"
)
TREE_CANOPY_IMAGE = (
    "https://imagery.dcgis.dc.gov/dcgis/rest/services/"
    "UFD/Urban_Tree_Canopy_2020/ImageServer"
)
TREE_CANOPY_BOUNDARY_QUERY = (
    "https://maps2.dcgis.dc.gov/dcgis/rest/services/"
    "DCGIS_DATA/Urban_Tree_Canopy/MapServer/4/query"
)
GEOFABRIK_PBF = (
    "https://download.geofabrik.de/north-america/us/"
    "district-of-columbia-latest.osm.pbf"
)
GEOFABRIK_SHP = (
    "https://download.geofabrik.de/north-america/us/"
    "district-of-columbia-latest-free.shp.zip"
)
NOAA_DEM_INDEX = "https://chs.coast.noaa.gov/htdata/raster5/elevation/DC_WashDC_DEM_2022_9838/"
NOAA_DEM_TIF = (
    "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/"
    "DC_WashDC_DEM_2022_9838/DTM_2022_1m.tif"
)
NOAA_DEM_VRT = (
    "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/"
    "DC_WashDC_DEM_2022_9838/DC_WashDC_DEM_2022_m9838_EPSG-26985.vrt"
)
NOAA_DEM_TILE_INDEX = (
    "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/dem/"
    "DC_WashDC_DEM_2022_9838/tileindex_DC_WashDC_DEM_2022.zip"
)
NOAA_LAZ_URLLIST = (
    "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/"
    "9837/urllist9837.txt"
)


@dataclass(frozen=True)
class DownloadRecord:
    """Metadata for one staged data file."""

    path: str
    source_url: str
    bytes: int
    description: str


class LinkParser(HTMLParser):
    """Minimal HTML link extractor for simple NOAA directory pages."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def request_session() -> requests.Session:
    """Create a requests session with a clear user agent."""

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def file_size(path: Path) -> int:
    """Return file size or zero when missing."""

    return path.stat().st_size if path.exists() else 0


def download_file(
    session: requests.Session,
    url: str,
    destination: Path,
    description: str,
    *,
    force: bool = False,
    attempts: int = 4,
) -> DownloadRecord:
    """Download a URL to disk using a temporary file and progress logging."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force and destination.stat().st_size > 0:
        print(f"exists: {destination} ({destination.stat().st_size:,} bytes)")
        return DownloadRecord(str(destination), url, destination.stat().st_size, description)

    tmp = destination.with_suffix(destination.suffix + ".tmp")
    for attempt in range(1, attempts + 1):
        try:
            print(f"download: {url} (attempt {attempt}/{attempts})")
            with session.get(url, stream=True, timeout=120) as response:
                response.raise_for_status()
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            break
        except Exception:
            if tmp.exists():
                tmp.unlink()
            if attempt >= attempts:
                raise
            time.sleep(min(30, 2**attempt))
    tmp.replace(destination)
    print(f"saved: {destination} ({destination.stat().st_size:,} bytes)")
    return DownloadRecord(str(destination), url, destination.stat().st_size, description)


def fetch_json(session: requests.Session, url: str, params: dict[str, Any] | None = None) -> Any:
    """Fetch JSON from an HTTP endpoint."""

    response = session.get(url, params=params, timeout=120)
    response.raise_for_status()
    return response.json()


def write_json(path: Path, payload: Any) -> None:
    """Write indented JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def download_arcgis_geojson(
    session: requests.Session,
    query_url: str,
    destination: Path,
    description: str,
    *,
    force: bool = False,
) -> DownloadRecord:
    """Download all records from an ArcGIS REST query endpoint as GeoJSON."""

    if destination.exists() and not force and destination.stat().st_size > 0:
        print(f"exists: {destination} ({destination.stat().st_size:,} bytes)")
        return DownloadRecord(str(destination), query_url, destination.stat().st_size, description)

    print(f"query: {query_url}")
    layer_info_url = query_url.rsplit("/", 1)[0]
    try:
        layer_info = fetch_json(session, layer_info_url, {"f": "json"})
        page_size = min(int(layer_info.get("maxRecordCount", 2000)), 2000)
    except Exception:
        page_size = 2000

    features: list[dict[str, Any]] = []
    offset = 0
    crs: dict[str, Any] | None = None
    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        payload = fetch_json(session, query_url, params)
        batch = payload.get("features", [])
        features.extend(batch)
        crs = crs or payload.get("crs")
        print(f"  fetched {len(features):,} features")
        if not payload.get("exceededTransferLimit") and len(batch) < page_size:
            break
        if not batch:
            break
        offset += len(batch)

    output = {"type": "FeatureCollection", "features": features}
    if crs:
        output["crs"] = crs
    write_json(destination, output)
    return DownloadRecord(str(destination), query_url, destination.stat().st_size, description)


def image_service_metadata(session: requests.Session, service_url: str) -> dict[str, Any]:
    """Return ArcGIS ImageServer metadata."""

    return fetch_json(session, service_url, {"f": "json"})


def export_image_tile(
    session: requests.Session,
    service_url: str,
    destination: Path,
    description: str,
    *,
    bbox: tuple[float, float, float, float],
    spatial_reference: int,
    pixel_size_m: float = 1.0,
    force: bool = False,
) -> DownloadRecord:
    """Export one GeoTIFF tile from an ArcGIS ImageServer."""

    xmin, ymin, xmax, ymax = bbox
    width = max(1, round((xmax - xmin) / pixel_size_m))
    height = max(1, round((ymax - ymin) / pixel_size_m))
    params = {
        "bbox": f"{xmin},{ymin},{xmax},{ymax}",
        "bboxSR": spatial_reference,
        "imageSR": spatial_reference,
        "size": f"{width},{height}",
        "format": "tiff",
        "pixelType": "U8",
        "noData": "255",
        "f": "image",
    }
    url = f"{service_url}/exportImage?{urlencode(params)}"
    return download_file(session, url, destination, description, force=force)


def export_center_image_tile(
    session: requests.Session,
    service_url: str,
    destination: Path,
    description: str,
    *,
    tile_size_m: int = 2048,
    force: bool = False,
) -> DownloadRecord:
    """Export a centered 1 m GeoTIFF sample tile from an ImageServer."""

    if destination.exists() and not force and destination.stat().st_size > 0:
        print(f"exists: {destination} ({destination.stat().st_size:,} bytes)")
        return DownloadRecord(str(destination), service_url, destination.stat().st_size, description)

    metadata = image_service_metadata(session, service_url)
    extent = metadata["extent"]
    spatial_reference = int(extent["spatialReference"].get("latestWkid") or extent["spatialReference"]["wkid"])
    cx = (float(extent["xmin"]) + float(extent["xmax"])) / 2.0
    cy = (float(extent["ymin"]) + float(extent["ymax"])) / 2.0
    half = tile_size_m / 2.0
    bbox = (cx - half, cy - half, cx + half, cy + half)
    destination.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )
    return export_image_tile(
        session,
        service_url,
        destination,
        description,
        bbox=bbox,
        spatial_reference=spatial_reference,
        force=force,
    )


def list_noaa_lidar_urls(session: requests.Session, destination: Path) -> list[str]:
    """Download and parse the NOAA 2022 DC LiDAR URL list."""

    record = download_file(
        session,
        NOAA_LAZ_URLLIST,
        destination,
        "NOAA 2022 DC OCTO LiDAR URL list",
    )
    lines = Path(record.path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


def download_noaa_dem_catalog(session: requests.Session, raw_lidar_dir: Path) -> list[DownloadRecord]:
    """Download NOAA DEM catalog metadata and return records."""

    records = [
        download_file(session, NOAA_DEM_VRT, raw_lidar_dir / "DC_WashDC_DEM_2022_EPSG-26985.vrt", "NOAA DEM VRT"),
        download_file(session, NOAA_DEM_TILE_INDEX, raw_lidar_dir / "tileindex_DC_WashDC_DEM_2022.zip", "NOAA DEM tile index"),
    ]
    try:
        html = session.get(NOAA_DEM_INDEX, timeout=60).text
        parser = LinkParser()
        parser.feed(html)
        links = [urljoin(NOAA_DEM_INDEX, link) for link in parser.links]
        (raw_lidar_dir / "noaa_dem_directory_links.json").write_text(
            json.dumps(links, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"warning: could not record NOAA DEM directory links: {exc}")
    return records


def create_osmnx_graph(root: Path, network_type: str = "walk") -> DownloadRecord | None:
    """Create a GraphML street graph using OSMnx when available."""

    graphml_path = root / "data" / "processed" / "streets" / f"dc_{network_type}_graph.graphml"
    if graphml_path.exists() and graphml_path.stat().st_size > 0:
        print(f"exists: {graphml_path} ({graphml_path.stat().st_size:,} bytes)")
        return DownloadRecord(
            str(graphml_path),
            "OSMnx graph_from_place('Washington, District of Columbia, USA')",
            graphml_path.stat().st_size,
            f"OSMnx {network_type} street graph",
        )

    try:
        import osmnx as ox
    except ImportError:
        print("warning: osmnx is not installed; skipping GraphML generation")
        return None

    print(f"osmnx: downloading {network_type} graph for Washington, DC")
    graph = ox.graph_from_place(
        "Washington, District of Columbia, USA",
        network_type=network_type,
        simplify=True,
    )
    graphml_path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(graph, graphml_path)
    return DownloadRecord(
        str(graphml_path),
        "OSMnx / OpenStreetMap via Overpass API",
        graphml_path.stat().st_size,
        f"OSMnx {network_type} street graph",
    )


def create_manifest(root: Path, records: list[DownloadRecord], *, sample_laz_count: int) -> None:
    """Write the bundle manifest."""

    manifest = {
        "aoi": "Washington, District of Columbia, USA",
        "created_at": datetime.now(UTC).isoformat(),
        "working_crs": {
            "rasters_preferred": "EPSG:26985 for NOAA DEM, EPSG:26918 for DC imagery services",
            "api_vectors": "EPSG:4326 GeoJSON",
        },
        "vertical_datum": "NAVD88 where available",
        "raster_resolution_m": "1 m where source supports it",
        "street_source": "OpenStreetMap / Geofabrik, with optional OSMnx GraphML",
        "lidar_source": "NOAA-hosted DC OCTO 2022 LiDAR and DEM products",
        "microclimate_model": (
            "SOLWEIG/SOLWEIG-GPU inputs staged; UTCI/Tmrt rasters must be generated "
            "from the processed DEM/DSM/canopy/meteorology stack."
        ),
        "notes": [
            "The default run downloads one representative COPC LAZ tile, not all 335 raw tiles.",
            "Run scripts/build_dc_data_bundle.py --download-all-laz to download the full NOAA point-cloud catalog.",
            "DC land-cover and tree-canopy ImageServer exports are staged as center sample tiles by default.",
        ],
        "sample_laz_count": sample_laz_count,
        "outputs": {
            "utci": "degrees Celsius, expected in data/processed/solweig_outputs/utci_YYYY-MM-DD_HH.tif",
            "tmrt": "degrees Celsius, expected in data/processed/solweig_outputs/tmrt_YYYY-MM-DD_HH.tif",
            "noise": "dBA or normalized edge proxy derived from DDOT AADT/BTS data",
            "slope": "percent rise derived from DEM",
            "canopy": "0-1 fraction or canopy height in meters",
        },
        "files": [asdict(record) for record in records],
    }
    write_json(root / "data" / "metadata" / "manifest.json", manifest)


def copy_processed_raster_inputs(root: Path) -> list[DownloadRecord]:
    """Stage raw files that are immediately usable as processed inputs."""

    def link_or_copy(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.stat().st_size == source.stat().st_size:
            return
        if destination.exists():
            destination.unlink()
        try:
            destination.hardlink_to(source)
        except OSError:
            shutil.copy2(source, destination)

    records: list[DownloadRecord] = []
    mappings = [
        (
            root / "data" / "raw" / "lidar" / "dem_2022_tiles" / "DTM_2022_1m.tif",
            root / "data" / "processed" / "rasters" / "dem_1m.tif",
            "NOAA 2022 DTM staged as processed DEM",
        ),
        (
            root / "data" / "raw" / "landcover" / "dc_generalized_landcover_2020_center_tile.tif",
            root / "data" / "processed" / "rasters" / "landcover_1m_center_tile.tif",
            "DC 2020 generalized land-cover center tile",
        ),
        (
            root / "data" / "raw" / "canopy" / "urban_tree_canopy_2020_center_tile.tif",
            root / "data" / "processed" / "rasters" / "canopy_1m_center_tile.tif",
            "DC 2020 urban tree canopy center tile",
        ),
        (
            root / "data" / "raw" / "lidar" / "dem_2022_tiles" / "DTM_2022_1m.tif",
            root / "data" / "processed" / "solweig_inputs" / "dem_1m.tif",
            "NOAA 2022 DTM staged as SOLWEIG DEM input",
        ),
        (
            root / "data" / "raw" / "landcover" / "dc_generalized_landcover_2020_center_tile.tif",
            root / "data" / "processed" / "solweig_inputs" / "landcover_1m_center_tile.tif",
            "DC 2020 generalized land-cover tile staged as SOLWEIG land-cover input",
        ),
        (
            root / "data" / "raw" / "canopy" / "urban_tree_canopy_2020_center_tile.tif",
            root / "data" / "processed" / "solweig_inputs" / "trees_cdsm_1m_center_tile.tif",
            "DC 2020 canopy tile staged as SOLWEIG vegetation input",
        ),
    ]
    for source, destination, description in mappings:
        if not source.exists():
            continue
        link_or_copy(source, destination)
        records.append(DownloadRecord(str(destination), str(source), destination.stat().st_size, description))
    return records


def main() -> int:
    """Entrypoint for the DC data bundle builder."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root directory.")
    parser.add_argument("--force", action="store_true", help="Re-download existing files.")
    parser.add_argument("--skip-dem", action="store_true", help="Skip the 590 MB NOAA full-city DEM.")
    parser.add_argument("--skip-osmnx", action="store_true", help="Skip OSMnx GraphML generation.")
    parser.add_argument("--sample-laz-tiles", type=int, default=1, help="Number of raw COPC LAZ tiles to download.")
    parser.add_argument("--download-all-laz", action="store_true", help="Download every NOAA 2022 COPC LAZ tile.")
    parser.add_argument("--image-tile-size-m", type=int, default=2048, help="Land-cover/canopy sample tile size.")
    args = parser.parse_args()

    root = args.root.resolve()
    session = request_session()
    records: list[DownloadRecord] = []

    records.append(
        download_arcgis_geojson(
            session,
            BOUNDARY_QUERY,
            root / "data" / "raw" / "boundary" / "dc_boundary.geojson",
            "Washington DC administrative boundary",
            force=args.force,
        )
    )
    records.append(download_file(session, GEOFABRIK_PBF, root / "data" / "raw" / "osm" / "district-of-columbia-latest.osm.pbf", "Geofabrik DC OSM PBF", force=args.force))
    records.append(download_file(session, GEOFABRIK_SHP, root / "data" / "raw" / "osm" / "district-of-columbia-latest-free.shp.zip", "Geofabrik DC free shapefile extract", force=args.force))

    if not args.skip_osmnx:
        graph_record = create_osmnx_graph(root, network_type="walk")
        if graph_record:
            records.append(graph_record)

    records.append(
        download_arcgis_geojson(
            session,
            TRAFFIC_VOLUME_QUERY,
            root / "data" / "raw" / "traffic_noise" / "ddot_traffic_volume_2023.geojson",
            "DDOT 2023 traffic volume lines",
            force=args.force,
        )
    )
    records.append(
        download_arcgis_geojson(
            session,
            TREE_CANOPY_BOUNDARY_QUERY,
            root / "data" / "raw" / "canopy" / "urban_tree_canopy_2020_by_dc_boundary.geojson",
            "DC 2020 urban tree canopy summary by DC boundary",
            force=args.force,
        )
    )
    records.append(
        export_center_image_tile(
            session,
            LAND_COVER_IMAGE,
            root / "data" / "raw" / "landcover" / "dc_generalized_landcover_2020_center_tile.tif",
            "DC 2020 generalized land-cover center GeoTIFF tile",
            tile_size_m=args.image_tile_size_m,
            force=args.force,
        )
    )
    records.append(
        export_center_image_tile(
            session,
            TREE_CANOPY_IMAGE,
            root / "data" / "raw" / "canopy" / "urban_tree_canopy_2020_center_tile.tif",
            "DC 2020 urban tree canopy center GeoTIFF tile",
            tile_size_m=args.image_tile_size_m,
            force=args.force,
        )
    )

    records.extend(download_noaa_dem_catalog(session, root / "data" / "raw" / "lidar"))
    if not args.skip_dem:
        records.append(
            download_file(
                session,
                NOAA_DEM_TIF,
                root / "data" / "raw" / "lidar" / "dem_2022_tiles" / "DTM_2022_1m.tif",
                "NOAA 2022 DC OCTO 1 m DEM/DTM GeoTIFF",
                force=args.force,
            )
        )

    laz_urls = list_noaa_lidar_urls(
        session,
        root / "data" / "raw" / "lidar" / "urllist9837.txt",
    )
    laz_tile_urls = [url for url in laz_urls if url.lower().endswith(".laz")]
    laz_to_download = laz_tile_urls if args.download_all_laz else laz_tile_urls[: max(0, args.sample_laz_tiles)]
    for url in laz_to_download:
        destination = root / "data" / "raw" / "lidar" / "laz" / Path(url).name
        records.append(download_file(session, url, destination, "NOAA 2022 DC OCTO raw COPC LAZ tile", force=args.force))

    records.extend(copy_processed_raster_inputs(root))
    create_manifest(root, records, sample_laz_count=len(laz_to_download))
    print(f"manifest: {root / 'data' / 'metadata' / 'manifest.json'}")
    print(f"total recorded bytes: {sum(record.bytes for record in records):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
