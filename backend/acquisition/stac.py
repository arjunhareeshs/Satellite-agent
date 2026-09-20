"""
Real STAC discovery for Sentinel-2 L2A and Sentinel-1 RTC.

Provider choice (validated live against both endpoints before selection):

  Sentinel-2  Element84 Earth Search, collection `sentinel-2-l2a`.
              AWS open data, no account and no API key. Assets are COGs served
              with HTTP range support, so an AOI clip is a windowed read rather
              than a 700 MB .SAFE download. Native CRS over this AOI is
              EPSG:32643 -- already the working CRS.

  Sentinel-1  Microsoft Planetary Computer, collection `sentinel-1-rtc`.
              RTC means ESA's calibration + terrain-correction chain has already
              been applied, which is what lets us skip the SNAP toolbox that PRD
              section 4.5 describes. Assets need a SAS token, issued anonymously.

  Copernicus  CDSE OData is queried separately (03b) purely to cross-reference
              each scene to its authoritative Copernicus product ID for the
              provenance record. Search there is unauthenticated.

Nothing in this module fabricates a scene. If the network is unavailable the
search raises rather than inventing a manifest.
"""

from __future__ import annotations

import datetime as dt
import os
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from shapely.geometry import box, shape

# --------------------------------------------------------------------------- config

EARTH_SEARCH_URL = os.getenv(
    "STAC_S2_ENDPOINT", "https://earth-search.aws.element84.com/v1"
)
S2_COLLECTION = os.getenv("STAC_S2_COLLECTION", "sentinel-2-l2a")

PLANETARY_COMPUTER_URL = os.getenv(
    "STAC_S1_ENDPOINT", "https://planetarycomputer.microsoft.com/api/stac/v1"
)
S1_COLLECTION = os.getenv("STAC_S1_COLLECTION", "sentinel-1-rtc")

CDSE_ODATA_URL = os.getenv(
    "CDSE_ODATA_ENDPOINT", "https://catalogue.dataspace.copernicus.eu/odata/v1"
)

# The six bands Prithvi-EO-2.0 expects, in its documented HLS order, mapped to
# Earth Search asset keys. B8A/B11/B12 are native 20 m and get resampled to the
# canonical 10 m grid on read.
S2_BAND_ASSETS: List[Tuple[str, str]] = [
    ("blue", "B02"),
    ("green", "B03"),
    ("red", "B04"),
    ("nir08", "B8A"),
    ("swir16", "B11"),
    ("swir22", "B12"),
]
S2_MASK_ASSET = "scl"
S2_VISUAL_ASSET = "visual"

S1_BAND_ASSETS: List[Tuple[str, str]] = [("vv", "VV"), ("vh", "VH")]


# --------------------------------------------------------------------------- clients


def _client(url: str, sign: bool = False):
    from pystac_client import Client

    if sign:
        import planetary_computer

        return Client.open(url, modifier=planetary_computer.sign_inplace)
    return Client.open(url)


def s2_client():
    return _client(EARTH_SEARCH_URL)


def s1_client():
    return _client(PLANETARY_COMPUTER_URL, sign=True)


# --------------------------------------------------------------------------- helpers


def aoi_intersection_ratio(item_geom: Dict[str, Any], aoi_bbox: Iterable[float]) -> float:
    """Fraction of the AOI covered by a STAC item's footprint."""
    aoi = box(*aoi_bbox)
    if aoi.area == 0:
        return 0.0
    try:
        footprint = shape(item_geom)
    except Exception:
        return 0.0
    if not footprint.is_valid:
        footprint = footprint.buffer(0)
    return footprint.intersection(aoi).area / aoi.area


def _month_key(datetime_str: str) -> str:
    return datetime_str[:7]


def _expected_months(start: str, end: str) -> List[str]:
    """Every YYYY-MM between start and end inclusive."""
    s = dt.date.fromisoformat(start[:10])
    e = dt.date.fromisoformat(end[:10])
    out, y, m = [], s.year, s.month
    while (y, m) <= (e.year, e.month):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def stratify_by_month(
    items: List[Dict[str, Any]],
    max_per_month: int,
    sort_key,
    start: str,
    end: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Temporal stratification, per PRD section 4.3.

    Taking the N least-cloudy scenes overall would load the archive with clear
    winter months and drop the monsoon entirely, which starves the seasonal
    baseline exactly where it needs observations. Instead cap the count per
    calendar month and report months that yielded nothing -- PRD section 4.3 is
    explicit that a coverage gap is itself a finding for the evaluation report.

    Returns (selected_items, coverage_gap_months).
    """
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in items:
        buckets[_month_key(item["datetime"])].append(item)

    selected: List[Dict[str, Any]] = []
    for month in sorted(buckets):
        ranked = sorted(buckets[month], key=sort_key)
        selected.extend(ranked[:max_per_month])

    gaps = [m for m in _expected_months(start, end) if m not in buckets]
    selected.sort(key=lambda it: it["datetime"])
    return selected, gaps


def _mgrs_from_props(props: Dict[str, Any]) -> Optional[str]:
    """Earth Search exposes the tile as three separate MGRS fields."""
    zone = props.get("mgrs:utm_zone")
    lat_band = props.get("mgrs:latitude_band")
    square = props.get("mgrs:grid_square")
    if zone is None or not lat_band or not square:
        return None
    return "%s%s%s" % (zone, lat_band, square)


# --------------------------------------------------------------------------- search


def search_sentinel2(
    aoi_bbox: Iterable[float],
    start: str,
    end: str,
    max_cloud: float = 30.0,
    min_intersection: float = 0.6,
    max_per_month: int = 3,
) -> Dict[str, Any]:
    """
    Search Earth Search for Sentinel-2 L2A scenes over the AOI.

    Metadata only -- no pixels are fetched here. PRD section 4.3: search before
    download.
    """
    aoi_bbox = list(aoi_bbox)
    client = s2_client()

    search = client.search(
        collections=[S2_COLLECTION],
        bbox=aoi_bbox,
        datetime="%sT00:00:00Z/%sT23:59:59Z" % (start, end),
        query={"eo:cloud_cover": {"lt": max_cloud}},
    )

    candidates: List[Dict[str, Any]] = []
    for item in search.items():
        props = item.properties
        ratio = aoi_intersection_ratio(item.geometry, aoi_bbox)
        if ratio < min_intersection:
            continue

        assets: Dict[str, str] = {}
        missing = False
        for asset_key, band_name in S2_BAND_ASSETS:
            asset = item.assets.get(asset_key)
            if asset is None:
                missing = True
                break
            assets[band_name] = asset.href
        if missing:
            continue

        scl = item.assets.get(S2_MASK_ASSET)
        if scl is None:
            continue
        assets["SCL"] = scl.href

        visual = item.assets.get(S2_VISUAL_ASSET)
        if visual is not None:
            assets["TCI"] = visual.href

        candidates.append(
            {
                "stac_id": item.id,
                "collection": S2_COLLECTION,
                "provider": "element84-earth-search",
                "sensor": "sentinel-2",
                "datetime": props["datetime"],
                "cloud_cover": float(props.get("eo:cloud_cover", 0.0)),
                "mgrs_tile": _mgrs_from_props(props),
                "epsg": props.get("proj:epsg"),
                "platform": props.get("platform"),
                "aoi_intersection": round(ratio, 4),
                "assets": assets,
            }
        )

    selected, gaps = stratify_by_month(
        candidates,
        max_per_month=max_per_month,
        sort_key=lambda it: it["cloud_cover"],
        start=start,
        end=end,
    )

    return {
        "sensor": "sentinel-2",
        "collection": S2_COLLECTION,
        "provider": "element84-earth-search",
        "endpoint": EARTH_SEARCH_URL,
        "searched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "aoi_bbox": aoi_bbox,
        "temporal_window": {"start": start, "end": end},
        "filters": {
            "max_cloud_cover": max_cloud,
            "min_aoi_intersection": min_intersection,
            "max_scenes_per_month": max_per_month,
        },
        "candidates_found": len(candidates),
        "total": len(selected),
        "coverage_gaps": gaps,
        "scenes": selected,
    }


def search_sentinel1(
    aoi_bbox: Iterable[float],
    start: str,
    end: str,
    min_intersection: float = 0.6,
    max_per_month: int = 3,
    relative_orbit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Search Planetary Computer for Sentinel-1 RTC scenes over the AOI.

    Orbit discipline matters here in a way it does not for optical. SAR
    backscatter depends on viewing geometry, so a trajectory built from mixed
    relative orbits carries a step change that has nothing to do with the
    ground. We therefore group by `sat:relative_orbit` and, unless one is named,
    keep only the track with the best coverage of the window.
    """
    aoi_bbox = list(aoi_bbox)
    client = s1_client()

    search = client.search(
        collections=[S1_COLLECTION],
        bbox=aoi_bbox,
        datetime="%sT00:00:00Z/%sT23:59:59Z" % (start, end),
    )

    candidates: List[Dict[str, Any]] = []
    for item in search.items():
        props = item.properties
        ratio = aoi_intersection_ratio(item.geometry, aoi_bbox)
        if ratio < min_intersection:
            continue

        assets: Dict[str, str] = {}
        missing = False
        for asset_key, band_name in S1_BAND_ASSETS:
            asset = item.assets.get(asset_key)
            if asset is None:
                missing = True
                break
            assets[band_name] = asset.href
        if missing:
            continue

        candidates.append(
            {
                "stac_id": item.id,
                "collection": S1_COLLECTION,
                "provider": "microsoft-planetary-computer",
                "sensor": "sentinel-1",
                "datetime": props["datetime"],
                "relative_orbit": props.get("sat:relative_orbit"),
                "orbit_state": props.get("sat:orbit_state"),
                "platform": props.get("platform"),
                "epsg": props.get("proj:epsg"),
                "aoi_intersection": round(ratio, 4),
                "assets": assets,
            }
        )

    orbit_counts: Dict[Any, int] = defaultdict(int)
    for c in candidates:
        orbit_counts[c["relative_orbit"]] += 1

    chosen_orbit = relative_orbit
    if chosen_orbit is None and orbit_counts:
        chosen_orbit = max(orbit_counts.items(), key=lambda kv: kv[1])[0]

    on_track = [c for c in candidates if c["relative_orbit"] == chosen_orbit]

    selected, gaps = stratify_by_month(
        on_track,
        max_per_month=max_per_month,
        sort_key=lambda it: -it["aoi_intersection"],
        start=start,
        end=end,
    )

    return {
        "sensor": "sentinel-1",
        "collection": S1_COLLECTION,
        "provider": "microsoft-planetary-computer",
        "endpoint": PLANETARY_COMPUTER_URL,
        "searched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "aoi_bbox": aoi_bbox,
        "temporal_window": {"start": start, "end": end},
        "filters": {
            "min_aoi_intersection": min_intersection,
            "max_scenes_per_month": max_per_month,
            "relative_orbit": chosen_orbit,
        },
        "orbit_distribution": {
            str(k): v for k, v in sorted(orbit_counts.items(), key=lambda kv: -kv[1])
        },
        "candidates_found": len(candidates),
        "total": len(selected),
        "coverage_gaps": gaps,
        "scenes": selected,
    }
