"""
nv/reportcard_full.py — Nevada Accountability Report Card (full per-entity crawl)

The Nevada Report Card "Data Interaction" (DI) portal — like the Arizona report
cards — exposes a clean JSON API once its endpoints are known (they're driven by
the SPA after dismissing its welcome modal). Two layers:

  1. Dashboard?year=Y&orgId=N
        Per-entity, per-year headline metrics: enrollment, graduation rate, ACT,
        teachers, attendance, bullying/cyber-bullying, reading/math proficiency by
        level, student/teacher ratio, star ratings. Works for STATE, every
        DISTRICT, and every SCHOOL.

  2. SummaryScores + Summary  (scope = <exam>.<yearcode>, report = summary_N)
        Detailed category breakdowns. Report number per exam (auto-discovered):
        SBAC e24, ACT e25, Graduation e32, Demographics/Enrollment e44, ...
        SummaryScores returns the valid score-measure IDs; Summary returns the
        data rows for the whole org collection (all entities) in one call.

This crawls Dashboard for every org × every year (the "state, each district, each
school, every year" request), and the detailed Summary for each working category
× year. Output under data/raw/nv/reportcard/.

Run:
    python scripts/nv/reportcard_full.py
Environment:
    NV_RC_MIN_YEAR=2014   earliest year (default; Dashboard has 2014-2025)
"""

import sys
import os
import json
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import tqdm

from common.http_client import make_session
from common.manifest import IncrementalManifest

API = "https://nevadareportcard.nv.gov/DIWAPI-NVReportCard/api/"
OUT_DIR = Path("data/raw/nv/reportcard")
MAX_WORKERS = 8

MIN_YEAR = int(os.environ.get("NV_RC_MIN_YEAR", "2014"))
MAX_YEAR = 2025

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://nevadareportcard.nv.gov/DI/",
    "Accept": "application/json, text/plain, */*",
}

LEVEL = {"S": "state", "D": "district", "B": "school"}

DASH_FIELDS = ["state", "level", "org_id", "org_name", "year", "status", "saved_path"]
DETAIL_FIELDS = ["state", "exam", "exam_name", "report", "year", "rows", "status", "saved_path"]

_thread_local = threading.local()


def _session():
    if not hasattr(_thread_local, "s"):
        _thread_local.s = make_session(headers=HEADERS)
    return _thread_local.s


def _get(path, params, retries=3):
    s = _session()
    for attempt in range(1, retries + 1):
        try:
            r = s.get(API + path, params=params, timeout=(10, 60))
            if r.status_code >= 400:
                return None, r.status_code
            try:
                return r.json(), 200
            except Exception:
                return r.text, 200
        except requests.RequestException:
            if attempt == retries:
                return None, "error"
            time.sleep(1.5 * attempt + random.random())


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Setup: orgs, year codes, exam codes, collection hash
# ---------------------------------------------------------------------------

def setup():
    s = make_session(headers=HEADERS)
    orgs = s.get(API + "organizations", timeout=30).json()
    scopes = s.get(API + "scopes", timeout=30).json()["scopes"]
    year_code = {int(x["value"]): x["code"] for x in scopes if x["type"] == "year"}
    exams = {x["code"]: x["value"] for x in scopes if x["type"] == "exam"}
    body = "=" + ",".join(str(o["id"]) for o in orgs)
    col = s.post(API + "organizationcollectionhash", data=body,
                 headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30).text.strip().strip('"')
    col = col if col.startswith("c") else "c" + col
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _save(OUT_DIR / "organizations.json", orgs)
    return orgs, year_code, exams, col


# ---------------------------------------------------------------------------
# Phase 1 — Dashboard per entity × year
# ---------------------------------------------------------------------------

def _dashboard_task(args):
    org, year, manifest = args
    level = LEVEL.get(org["type"], "unknown")
    data, status = _get("Dashboard", {"year": year, "orgId": org["id"]})
    saved = ""
    if isinstance(data, list) and data and str(data[0].get("enrollment", "")).strip() not in ("", "None"):
        dest = OUT_DIR / "dashboard" / level / str(org["id"]) / f"{year}.json"
        _save(dest, data)
        saved = str(dest)
        status = "saved"
    else:
        status = "empty" if status == 200 else status
    manifest.append({"state": "NV", "level": level, "org_id": org["id"],
                     "org_name": org.get("name", ""), "year": year,
                     "status": status, "saved_path": saved})


def crawl_dashboard(orgs, manifest):
    years = list(range(MIN_YEAR, MAX_YEAR + 1))
    tasks = [(o, y, manifest) for o in orgs for y in years]
    print(f"Dashboard: {len(orgs)} orgs × {len(years)} years = {len(tasks)} calls")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(_dashboard_task, t) for t in tasks]
        for _ in tqdm.tqdm(as_completed(futs), total=len(futs), desc="Dashboard"):
            pass


# ---------------------------------------------------------------------------
# Phase 2 — detailed Summary per category × year
# ---------------------------------------------------------------------------

def _discover_report(col, scope):
    """Find the summary_N report that yields score measures for this scope."""
    best = (None, 0)
    for n in range(1, 9):
        data, _ = _get("SummaryScores", {"organization": col, "scope": scope, "report": f"summary_{n}"})
        if isinstance(data, list):
            cnt = sum(len(g.get("summaryScoreMeasure", [])) for g in data)
            if cnt > best[1]:
                best = (f"summary_{n}", cnt)
    return best[0]


def _score_ids(col, scope, report):
    data, _ = _get("SummaryScores", {"organization": col, "scope": scope, "report": report})
    ids = []
    if isinstance(data, list):
        def walk(g):
            for m in g.get("summaryScoreMeasure", []):
                if m.get("id"):
                    ids.append(m["id"])
                walk(m)
        for g in data:
            walk(g)
    return ids


def crawl_detail(year_code, exams, col, manifest):
    years = [y for y in range(MIN_YEAR, MAX_YEAR + 1) if y in year_code]
    # discover the working report# per exam once (using the latest year)
    latest = year_code[max(years)]
    working = {}
    for code, name in tqdm.tqdm(exams.items(), desc="Discovering exams"):
        rep = _discover_report(col, f"{code}.{latest}")
        if rep:
            working[code] = (name, rep)
    print(f"Detail: {len(working)} categories with data: {[v[0] for v in working.values()]}")

    tasks = [(code, name, rep, y) for code, (name, rep) in working.items() for y in years]
    for code, name, rep, year in tqdm.tqdm(tasks, desc="Summary detail"):
        scope = f"{code}.{year_code[year]}"
        scores = _score_ids(col, scope, rep)
        if not scores:
            manifest.append({"state": "NV", "exam": code, "exam_name": name, "report": rep,
                             "year": year, "rows": "", "status": "no_scores", "saved_path": ""})
            continue
        data, status = _get("Summary", {"organization": col, "scope": scope, "report": rep,
                                        "num": 10000, "page": 1, "pagesize": 10000,
                                        "domain": str(name).lower(), "scores": ",".join(scores)})
        rows = ""
        saved = ""
        if isinstance(data, dict) and data.get("data", {}).get("rows"):
            rows = data.get("total_data_count", len(data["data"]["rows"]))
            dest = OUT_DIR / "detail" / code / f"{year}.json"
            _save(dest, data)
            saved = str(dest)
            status = "saved"
        else:
            status = "empty" if status == 200 else status
        manifest.append({"state": "NV", "exam": code, "exam_name": name, "report": rep,
                         "year": year, "rows": rows, "status": status, "saved_path": saved})
        time.sleep(0.2)


def main():
    print("Setting up (orgs, scopes, collection)...")
    orgs, year_code, exams, col = setup()
    print(f"  {len(orgs)} orgs (1 state, "
          f"{sum(1 for o in orgs if o['type']=='D')} districts, "
          f"{sum(1 for o in orgs if o['type']=='B')} schools); collection {col}")

    dash_mf = IncrementalManifest(OUT_DIR / "dashboard_manifest.csv", DASH_FIELDS,
                                  key=["level", "org_id", "year"])
    crawl_dashboard(orgs, dash_mf)

    detail_mf = IncrementalManifest(OUT_DIR / "detail_manifest.csv", DETAIL_FIELDS,
                                    key=["exam", "report", "year"])
    crawl_detail(year_code, exams, col, detail_mf)

    dash_mf.finalize()
    detail_mf.finalize()

    print(f"\nDone. Output: {OUT_DIR}")


if __name__ == "__main__":
    main()
