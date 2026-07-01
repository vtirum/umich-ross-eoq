"""
nv/download.py — Nevada (NDE) Report Card API data collection

The Nevada Report Card "Data Interaction" API (nevadareportcard.nv.gov) exposes
all data as CSV via a 3-step flow (reverse-engineered, and confirmed against the
documented `nevadaReportCardr` R package):

  1. GET  /api/organizations
         -> all 967 orgs (state 'S', district 'D', school/building 'B')
  2. POST /api/organizationcollectionhash   body="=id1,id2,..."
         -> a collection id (prefix with 'c') representing that set of orgs
  3. GET  /api/summaryCSV?report=summary_1&organization=c<id>&scope=<scope>&scores=<scores>
         -> CSV with one row per org for the requested dataset/year(s)

`scope` = "<dataset>.<year>[.<year>...][.g3.g4...]" and each dataset has a fixed
`scores` field list. Dataset codes (from the R package):
  e24 SBAC assessment (grades 3-8), e25 ACT, e9 fiscal, e20 graduation,
  e12 personnel, e7 demographics, e11 CTE, e10 student, e8 technology.

One collection (all orgs) + one summaryCSV per dataset×year = full state/
district/school coverage. Output: data/raw/nv/<dataset>/<year>.csv

Run:
    python scripts/nv/download.py
Environment:
    NV_MIN_YEAR=2019   earliest spring year to pull (default; spans to current)
    NV_MAX_YEAR=2025   latest spring year to pull (default current)
"""

import sys
import os
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm

from common.file_utils import sha256_file
from common.http_client import make_session
from common.manifest import IncrementalManifest

API = "https://nevadareportcard.nv.gov/DIWAPI-NVReportCard/api/"
OUT_DIR = Path("data/raw/nv")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

MIN_YEAR = int(os.environ.get("NV_MIN_YEAR", "2019"))
MAX_YEAR = int(os.environ.get("NV_MAX_YEAR", "2025"))
YEARS = list(range(MIN_YEAR, MAX_YEAR + 1))

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

SBAC_GRADES = [f"g{g}" for g in range(3, 9)]

# Each dataset: code, score field list, grades.
# Exam codes and score fields discovered by capturing network traffic from
# nevadareportcard.nv.gov/di/main/assessment via Playwright.
DATASETS = [
    {"name": "assessment_sbac", "code": "e24", "grades": SBAC_GRADES,
     "scores": "N_MA,N_RD,N_SC,MA_NotTested,RD_NotTested,MA_Tested,RD_Tested,MA_pass,RD_pass,SC_pass,MA_level,RD_level,SC_level"},
    {"name": "assessment_ccr_grade11", "code": "e25", "grades": [],
     "scores": "N_MA,N_ELA,MA_NotTested,ELA_NotTested,MA_Tested,ELA_Tested,MA_Pass,ELA_Pass,MA_level,ELA_level"},
    {"name": "assessment_science_5_8", "code": "e30", "grades": [],
     "scores": "N_SC,SC_NotTested,SC_Tested,SC_pass,SC_level"},
    {"name": "assessment_science_9_10", "code": "e29", "grades": [],
     "scores": "N,SC_NotTested,SC_Tested,pass,level"},
    {"name": "assessment_naa", "code": "e31", "grades": [],
     "scores": "MA_EA,RD_EA,SC_EA,MA_level,RD_level,SC_level"},
    {"name": "assessment_elpa", "code": "e39", "grades": [],
     "scores": "N_Compo,Compo_Tested,Compo_NotTested,Compo_Pro,CO"},
]

# DEFERRED — non-assessment datasets. The NV API's summaryCSV requires
# *exam-specific* numeric score IDs. The score IDs documented in the
# nevadaReportCardr R package belong to RETIRED exam codes (e20 grad, e7 demo,
# etc.); the current exam codes (e32 4yr-cohort grad, e44 demographics,
# e40 discipline 2022+, e9 fiscal, e12 personnel, e34 CTE, e10 students) return
# HTTP 500 "Sequence contains no matching element" when queried with those old
# score IDs. Collecting them requires discovering each current exam's valid
# score IDs (via a portal metadata endpoint or network capture of the DI site).
# Tracked as a follow-up; see docs/coverage_matrix.md.
DEFERRED_EXAM_CODES = {
    "graduation_4yr": "e32", "graduation_5yr": "e28", "demographics": "e44",
    "discipline": "e40", "fiscal": "e9", "per_pupil_spending": "e36",
    "personnel": "e12", "professional_qual": "e45", "cte_enrollment": "e34",
    "students": "e10", "chronic_absenteeism": "e33", "technology": "e8",
}

MANIFEST_FIELDS = [
    "state", "dataset", "year", "scope", "local_path",
    "status", "rows", "size_bytes", "sha256",
]


def get_year_codes(session):
    """Map calendar (spring) year -> NRC scope code (e.g. 2024 -> 'y21')."""
    scopes = session.get(API + "scopes", timeout=30).json()["scopes"]
    return {int(s["value"]): s["code"] for s in scopes if s["type"] == "year"}


def get_collection(session):
    """Fetch all orgs and POST them to get one collection id covering every entity."""
    orgs = session.get(API + "organizations", timeout=30).json()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "organizations.json", "w") as f:
        json.dump(orgs, f, indent=2)
    ids = [str(o["id"]) for o in orgs]
    body = "=" + ",".join(ids)
    r = session.post(API + "organizationcollectionhash", data=body,
                     headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    r.raise_for_status()
    col = r.text.strip().strip('"')
    return (col if col.startswith("c") else "c" + col), len(orgs)


def _pull(session, col_id, ds, year_codes):
    """One call per dataset covering all requested years (multi-year scope)."""
    scope = ".".join([ds["code"]] + year_codes + ds["grades"])
    url = (f"{API}summaryCSV?report=summary_1&organization={col_id}"
           f"&scope={scope}&scores={ds['scores']}")
    dest = OUT_DIR / ds["name"] / "all_years.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)

    row = {
        "state": "NV", "dataset": ds["name"], "year": "all", "scope": scope,
        "local_path": str(dest), "status": "", "rows": "", "size_bytes": "", "sha256": "",
    }
    if dest.exists() and dest.stat().st_size > 0:
        row.update(status="skipped_existing", size_bytes=dest.stat().st_size,
                   rows=max(0, sum(1 for _ in open(dest)) - 1), sha256=sha256_file(dest))
        return row

    resp = session.get(url, timeout=180)
    if resp.status_code >= 400:
        row["status"] = f"http_{resp.status_code}"
        return row
    text = resp.text
    nrows = text.count("\n")
    if nrows <= 1 or len(text) < 50:
        row["status"] = "empty"
        return row
    dest.write_text(text, encoding="utf-8")
    row.update(status="downloaded", size_bytes=dest.stat().st_size,
               rows=max(0, nrows - 1), sha256=sha256_file(dest))
    return row


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)

    print("Fetching year codes + building org collection...")
    year_map = get_year_codes(session)
    year_codes = [year_map[y] for y in YEARS if y in year_map]
    col_id, n_orgs = get_collection(session)
    print(f"  {n_orgs} orgs -> collection {col_id}")
    print(f"  years {YEARS[0]}-{YEARS[-1]} -> codes {year_codes}")
    print(f"  working datasets: {[d['name'] for d in DATASETS]}")
    print(f"  deferred (need per-exam score IDs): {list(DEFERRED_EXAM_CODES)}")

    manifest = IncrementalManifest(MANIFEST_PATH, MANIFEST_FIELDS)
    saved = 0
    for ds in tqdm.tqdm(DATASETS, desc="NV datasets"):
        try:
            row = _pull(session, col_id, ds, year_codes)
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {ds['name']}: {e}")
            row = {"state": "NV", "dataset": ds["name"], "year": "all", "scope": "",
                   "local_path": "", "status": f"error:{str(e)[:50]}", "rows": "",
                   "size_bytes": "", "sha256": ""}
        manifest.append(row)
        if row["status"] in ("downloaded", "skipped_existing"):
            saved += 1
        time.sleep(0.5)

    print(f"\nDone. {saved}/{len(DATASETS)} dataset CSVs. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
