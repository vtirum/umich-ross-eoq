"""
fl/report_cards.py — Florida Report Card API data collection

Mirrors az/report_cards_reports.py exactly:
  - Pure requests, no browser
  - Discovers all districts and schools via list endpoints
  - For each entity × content endpoint, fetches JSON and saves to disk
  - IncrementalManifest (crash-safe, thread-safe)
  - ThreadPoolExecutor for parallelism

API structure (confirmed by network inspection):
  Host:      https://edudata.fldoe.org
  Entity ID: 6-digit string — first 2 digits = district, last 4 = school
             State level:   000000
             District 01:   010000
             School 0221 in district 01:  010221

  Content endpoints:
    GET /api/RCContent/{EndpointName}/{entity_id}
    Returns JSON (list of rows, usually multi-year)

  List endpoints:
    GET /api/Dropdown/GetDistrictList/
      → {"results": [{"id": "01", "text": "ALACHUA"}, ...]}
    GET /api/Dropdown/GetSchoolList/
      → {"results": [{"text": "ALACHUA", "children": [{"id": "010221", ...}]}, ...]}
      The school id IS the 6-digit entity_id.

Run:
    python scripts/fl/report_cards.py

Outputs to data/raw/fl/report_cards/
"""

import sys
import json
import threading
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import tqdm

from common.http_client import make_session
from common.manifest import IncrementalManifest

API_HOST = "https://edudata.fldoe.org"
OUT_DIR = Path("data/raw/fl/report_cards")
MAX_WORKERS = 8

# The x-requested-with header is REQUIRED — the server returns HTTP 400 without it.
# This is the jQuery AJAX marker the report card API validates against.
_API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{API_HOST}/ReportCards/Schools.html",
}

# Content endpoints differ by entity level — confirmed by capturing the XHR calls
# the report card pages make at state, district, and school levels.
# Entity ID (6 digits: DDSSSS) is substituted as the final path segment.
STATE_ENDPOINTS = [
    "GetBase", "GetEnrollment", "GetGradLine", "GetGradeCounts",
    "GetParticipation", "GetSchoolCounts", "GetSupportCount", "GetTGELA",
]

DISTRICT_ENDPOINTS = [
    "GetBase", "GetEnrollment", "GetGradLine", "GetGradeCounts",
    "GetParticipationBoxes", "GetSchoolCounts", "GetSchoolSupport",
    "GetSupportCount", "GetTGELA",
]

SCHOOL_ENDPOINTS = [
    "GetBase", "GetEnrollment", "GetGradLine",
    "GetParticipationBoxes", "GetSchoolSupport", "GetTGELA",
]

ENDPOINTS_BY_LEVEL = {
    "state": STATE_ENDPOINTS,
    "district": DISTRICT_ENDPOINTS,
    "school": SCHOOL_ENDPOINTS,
}

# Static reference files — fetched once, not per entity
STATIC_FILES = [
    f"{API_HOST}/ReportCards/data/config.json",
    f"{API_HOST}/ReportCards/data/datadictionary.json",
    f"{API_HOST}/ReportCards/data/ADADict.json",
]

DISTRICT_LIST_URL = f"{API_HOST}/api/Dropdown/GetDistrictList/"
SCHOOL_LIST_URL   = f"{API_HOST}/api/Dropdown/GetSchoolList/"

STATE_ENTITY_ID = "000000"

MANIFEST_FIELDS = [
    "entity_id", "district", "school", "entity_type",
    "endpoint", "status_code", "saved_path",
]

_thread_local = threading.local()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get_session():
    if not hasattr(_thread_local, "session"):
        _thread_local.session = make_session(headers=_API_HEADERS)
    return _thread_local.session


def _entity_referer(district, school):
    """The API selects the entity from the Referer query string, NOT the URL path.
    A Referer of Schools.html?school=SSSS&district=DD makes the server return that
    entity's data regardless of the path segment."""
    return f"{API_HOST}/ReportCards/Schools.html?school={school}&district={district}"


def _call(url, params=None, referer=None):
    """GET url and return (data, status_code). Retries on transient errors.

    referer: per-request Referer header. REQUIRED for RCContent endpoints — the
    server reads district/school from its query string to pick the entity.
    """
    session = _get_session()
    headers = {"Referer": referer} if referer else None
    for attempt in range(1, 4):
        try:
            resp = session.get(url, params=params or {}, headers=headers, timeout=(10, 60))
            if resp.status_code in (204, 400, 403, 404):
                return None, resp.status_code
            resp.raise_for_status()
            try:
                return resp.json(), resp.status_code
            except Exception:
                return resp.text, resp.status_code
        except requests.RequestException:
            if attempt == 3:
                return None, "error"
            time.sleep(2 * attempt + random.random())


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Entity lists
# ---------------------------------------------------------------------------

def get_district_ids():
    """Return a list of 2-digit district ID strings, e.g. ['01', '02', ...]."""
    data, status = _call(DISTRICT_LIST_URL)
    if not data:
        raise RuntimeError(f"GetDistrictList failed (status={status})")
    results = data.get("results", data) if isinstance(data, dict) else data
    ids = [d["id"] for d in results if isinstance(d, dict) and d.get("id")]
    print(f"  {len(ids)} districts")
    return ids


def get_all_school_entity_ids():
    """
    Return a flat list of 6-digit entity IDs for every school in Florida.
    GetSchoolList returns all schools grouped by district in one call:
      [{"text": "ALACHUA", "children": [{"id": "010221", ...}, ...]}, ...]
    The child id IS the 6-digit entity_id used in content endpoint URLs.
    """
    data, status = _call(SCHOOL_LIST_URL)
    if not data:
        raise RuntimeError(f"GetSchoolList failed (status={status})")
    results = data.get("results", data) if isinstance(data, dict) else data

    entity_ids = []
    for group in results:
        if isinstance(group, dict):
            for child in group.get("children", []):
                if isinstance(child, dict) and child.get("id"):
                    entity_ids.append(child["id"])  # already 6-digit
    print(f"  {len(entity_ids)} schools")
    return entity_ids


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def _collect_entity(entity_id, entity_type, manifest):
    """Fetch all content endpoints for one entity and append rows to manifest."""
    district = entity_id[:2]
    school   = entity_id[2:]
    referer  = _entity_referer(district, school)

    for ep_name in ENDPOINTS_BY_LEVEL[entity_type]:
        url = f"{API_HOST}/api/RCContent/{ep_name}/{entity_id}"
        data, status = _call(url, referer=referer)

        out_path = (
            OUT_DIR / entity_type
            / f"district_{district}"
            / f"school_{school}"
            / f"{ep_name}.json"
        )

        if data is not None:
            _save_json(out_path, data)

        manifest.append({
            "entity_id":   entity_id,
            "district":    district,
            "school":      school,
            "entity_type": entity_type,
            "endpoint":    ep_name,
            "status_code": status,
            "saved_path":  str(out_path) if data is not None else "",
        })


def _worker(args):
    entity_id, entity_type, manifest = args
    _collect_entity(entity_id, entity_type, manifest)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Fetch static reference files once (config, data dictionary, ADA dict)
    static_dir = OUT_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    for url in STATIC_FILES:
        data, _ = _call(url)
        if data is not None:
            fname = url.split("/")[-1]
            _save_json(static_dir / fname, data)
            print(f"  Saved static: {fname}")

    manifest = IncrementalManifest(OUT_DIR / "manifest.csv", MANIFEST_FIELDS)

    # ---- State level -------------------------------------------------------
    print("\nFetching state-level data...")
    _collect_entity(STATE_ENTITY_ID, "state", manifest)

    # ---- District level ----------------------------------------------------
    print("\nFetching district list...")
    district_ids = get_district_ids()

    # District entity_id = district code + "0000"
    district_tasks = [
        (f"{d}0000", "district", manifest)
        for d in district_ids
    ]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_worker, t): t for t in district_tasks}
        for future in tqdm.tqdm(as_completed(futures), total=len(futures), desc="Districts"):
            try:
                future.result()
            except Exception as e:
                tqdm.tqdm.write(f"District error: {e}")

    # ---- School level ------------------------------------------------------
    print("\nFetching school list...")
    school_entity_ids = get_all_school_entity_ids()

    school_tasks = [
        (eid, "school", manifest)
        for eid in school_entity_ids
    ]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_worker, t): t for t in school_tasks}
        for future in tqdm.tqdm(as_completed(futures), total=len(futures), desc="Schools"):
            try:
                future.result()
            except Exception as e:
                tqdm.tqdm.write(f"School error: {e}")

    total = sum(1 for _ in open(OUT_DIR / "manifest.csv")) - 1  # subtract header
    print(f"\nDone. {total} rows written. Manifest: {OUT_DIR / 'manifest.csv'}")


if __name__ == "__main__":
    main()
