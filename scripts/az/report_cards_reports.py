"""
Arizona School Report Cards API (azreportcards.azed.gov).

The richest Arizona source: 23 report endpoints per entity, for the state, every
district and every school, across FY2018-2025. Plain JSON, no auth. Entities come
from GetEntityList; reports are fetched concurrently and written to
data/raw/az/reportcards/<year>/<level>/<entity>/<report>.json.

Roughly 71,500 files per year. A third to two thirds of responses are `[]` - the
endpoint exists but has nothing for that entity - which is expected, and more common
in the older years.

    python scripts/az/report_cards_reports.py
    AZ_RC_YEARS=2019,2020 python scripts/az/report_cards_reports.py   # narrow the run
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import threading
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests
import tqdm

from common.http_client import make_session
from common.manifest import IncrementalManifest

BASE = "https://azreportcards.azed.gov/api"
OUT_DIR = Path("data/raw/az/reportcards")
OUT_DIR.mkdir(parents=True, exist_ok=True)

STATE_ENTITY_ID = 79275
MAX_WORKERS = 8

_API_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://azreportcards.azed.gov/",
}

MANIFEST_FIELDS = [
    "fiscal_year", "entity_id", "entity_name", "entity_kind",
    "report", "url", "status_code", "saved_path",
]

REPORT_ENDPOINTS = [
    {"name": "Student Enrollment", "path": "DataApi/Student Enrollment", "params": {"reportSection": "Student Enrollment"}},
    {"name": "Teacher Qualification", "path": "DataApi/Teacher Qualification", "params": {"reportSection": "Teacher Qualification"}},
    {"name": "Assessment Proficiency Level", "path": "DataApi/Assessment Proficiency Level", "params": {"reportSection": "Assessment Proficiency Level"}},
    {"name": "ALT Assessment Participation Rates", "path": "DataApi/ALT Assessment Participation Rates", "params": {"reportSection": "ALT Assessment Participation Rates"}},
    {"name": "Assessment Participation Rates", "path": "DataApi/Assessment Participation Rates", "params": {"reportSection": "Assessment Participation Rates"}},
    {"name": "Federal Proficiency Goals", "path": "DataApi/Federal Proficiency Goals", "params": {"reportSection": "Federal Proficiency Goals"}},
    {"name": "Assessment DetailsFAY", "path": "DataApi/Assessment DetailsFAY", "params": {"reportSection": "Assessment DetailsFAY"}},
    {"name": "EL Proficiency", "path": "DataApi/EL Proficiency", "params": {"reportSection": "EL Proficiency"}},
    {"name": "Preschool Progress Monitoring", "path": "DataApi/Preschool Progress Monitoring", "params": {"reportSection": "Preschool Progress Monitoring"}},
    {"name": "Graduation Rate", "path": "DataApi/Graduation Rate", "params": {"reportSection": "Graduation Rate"}},
    {"name": "Graduation Rate Report Type 2", "path": "DataApi/Graduation Rate", "params": {"reportSection": "Graduation Rate", "reportTypeId": 2}},
    {"name": "End Of Year Promotion", "path": "DataApi/End Of Year Promotion", "params": {"reportSection": "End Of Year Promotion", "reportTypeId": 1}},
    {"name": "LRE for Preschool SPED Students", "path": "DataApi/LRE for Preschool SPED Students", "params": {"reportSection": "LRE for Preschool SPED Students"}},
    {"name": "GetRAELCount", "path": "DataApi/GetRAELCount", "params": {}},
    {"name": "GetTeachersTrendData", "path": "DataApi/GetTeachersTrendData", "params": {}},
    {"name": "GetELProficiencyTrendData", "path": "DataApi/GetELProficiencyTrendData", "params": {}},
    {"name": "GetGradRateTrendData", "path": "DataApi/GetGradRateTrendData", "params": {}},
    {"name": "GetDropoutRateTrendData", "path": "DataApi/GetDropoutRateTrendData", "params": {}},
    {"name": "GetEnrollmentTrendData", "path": "DataApi/GetEnrollmentTrendData", "params": {}},
    {"name": "GetAssessmentTrendData", "path": "DataApi/GetAssessmentTrendData", "params": {}},
    {"name": "Federal Graduation Rate Goals", "path": "DataApi/Federal Graduation Rate Goals", "params": {}},
    {"name": "GetELProficiencyActuals", "path": "DataApi/GetELProficiencyActuals", "params": {}},
    {"name": "GetChronicAbsenteeismTrendData", "path": "DataApi/GetChronicAbsenteeismTrendData", "params": {}},
]

# Thread-local sessions so each worker thread has its own connection pool.
_thread_local = threading.local()


def _get_thread_session():
    if not hasattr(_thread_local, "session"):
        _thread_local.session = make_session(headers=_API_HEADERS)
    return _thread_local.session


def _safe_name(text):
    return (
        text.replace("/", "_").replace("\\", "_").replace(" ", "_")
        .replace("%20", "_").replace("?", "_").replace("&", "_")
    )


def _api_url(path):
    return f"{BASE}/{quote(path, safe='/')}"


def _get_json(session, path, params=None):
    url = _api_url(path)
    for attempt in range(1, 4):
        try:
            response = session.get(url, params=params or {}, headers=_API_HEADERS, timeout=(10, 60))
            if response.status_code == 204:
                return None, response.url, response.status_code
            if response.status_code in [400, 403, 404, 500]:
                return None, response.url, response.status_code
            response.raise_for_status()
            try:
                return response.json(), response.url, response.status_code
            except Exception:
                return response.text, response.url, response.status_code
        except requests.RequestException as e:
            if attempt == 3:
                return None, url, "connection_error"
            time.sleep(3 * attempt + random.random())


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_fiscal_years(session):
    data, url, status = _get_json(session, "DataApi/GetFiscalYears")
    if not data:
        raise RuntimeError(f"Failed to fetch fiscal years (status={status}, url={url})")
    return [row["fiscalYear"] for row in data]


def get_entities(session, fiscal_year):
    data, url, status = _get_json(session, "Entity/GetEntityList", {"fiscalYear": fiscal_year})
    if data is None:
        raise RuntimeError(f"Failed to fetch entity list for FY{fiscal_year} (status={status})")
    _save_json(OUT_DIR / str(fiscal_year) / "entities" / "entity_list.json", data)
    return data


def _classify_entity(entity):
    entity_type = str(entity.get("entityType", "")).lower()
    school_types = str(entity.get("schoolTypes", "")).lower()
    if entity_type == "school":
        return "school"
    if entity_type == "lea" or "district" in school_types:
        return "district"
    return "unknown"


def _download_report(session, fiscal_year, entity, report):
    entity_id = entity["educationOrganizationId"]
    entity_kind = _classify_entity(entity)

    params = dict(report["params"])
    params["fiscalYear"] = fiscal_year
    params["educationOrganizationId"] = entity_id

    data, final_url, status = _get_json(session, report["path"], params)

    report_name = _safe_name(report["name"])
    out_path = OUT_DIR / str(fiscal_year) / entity_kind / str(entity_id) / f"{report_name}.json"

    if data is not None:
        _save_json(out_path, data)

    return {
        "fiscal_year": fiscal_year,
        "entity_id": entity_id,
        "entity_name": entity.get("nameOfInstitution"),
        "entity_kind": entity_kind,
        "report": report["name"],
        "url": final_url,
        "status_code": status,
        "saved_path": str(out_path) if data is not None else "",
    }


def _download_state_report(session, fiscal_year, report):
    fake_entity = {
        "educationOrganizationId": STATE_ENTITY_ID,
        "nameOfInstitution": "Arizona State Level",
        "entityType": "State",
        "schoolTypes": "State",
    }
    row = _download_report(session, fiscal_year, fake_entity, report)

    old_path = Path(row["saved_path"]) if row["saved_path"] else None
    if old_path and old_path.exists():
        new_path = OUT_DIR / str(fiscal_year) / "state" / f"{_safe_name(report['name'])}.json"
        new_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.replace(new_path)
        row["saved_path"] = str(new_path)
        row["entity_kind"] = "state"

    return row


def _worker(args):
    fiscal_year, entity, report = args
    return _download_report(_get_thread_session(), fiscal_year, entity, report)


def main():
    manifest = IncrementalManifest(OUT_DIR / "manifest.csv", MANIFEST_FIELDS,
                                   key=["fiscal_year", "entity_id", "report"])

    bootstrap_session = make_session(headers=_API_HEADERS)
    fiscal_years = get_fiscal_years(bootstrap_session)
    # The API serves FY2018-2025. This used to take only the last year, which left six
    # years unfetched; AZ_RC_YEARS=2019,2020 narrows a run without editing the file.
    want = os.environ.get("AZ_RC_YEARS", "").strip()
    if want:
        keep = {int(y) for y in re.split(r"[,\s]+", want) if y}
        fiscal_years = [y for y in fiscal_years if int(y) in keep]
    print("Fiscal years:", fiscal_years)

    for fiscal_year in fiscal_years:
        print(f"\n=== Fiscal Year {fiscal_year} ===")

        sections, _, _ = _get_json(
            bootstrap_session,
            "DataApi/GetSateReportSections",
            {"reportSection": "GetSateReportSections", "fiscalYear": fiscal_year},
        )
        if sections is not None:
            _save_json(OUT_DIR / str(fiscal_year) / "state" / "state_report_sections.json", sections)

        print(f"Fetching {len(REPORT_ENDPOINTS)} state-level reports...")
        for report in tqdm.tqdm(REPORT_ENDPOINTS, desc="State reports"):
            row = _download_state_report(bootstrap_session, fiscal_year, report)
            manifest.append(row)

        entities = get_entities(bootstrap_session, fiscal_year)
        print(f"Found {len(entities)} entities — dispatching {len(entities) * len(REPORT_ENDPOINTS)} requests across {MAX_WORKERS} workers")

        tasks = [
            (fiscal_year, entity, report)
            for entity in entities
            for report in REPORT_ENDPOINTS
            if entity.get("educationOrganizationId")
        ]

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_worker, task): task for task in tasks}
            for future in tqdm.tqdm(as_completed(futures), total=len(tasks), desc=f"FY{fiscal_year} entities"):
                try:
                    manifest.append(future.result())
                except Exception as e:
                    task = futures[future]
                    tqdm.tqdm.write(f"Worker failed {task[1].get('nameOfInstitution')} / {task[2]['name']}: {e}")

    manifest.finalize()
    print(f"\nDone. Manifest: {OUT_DIR / 'manifest.csv'}")


if __name__ == "__main__":
    main()
