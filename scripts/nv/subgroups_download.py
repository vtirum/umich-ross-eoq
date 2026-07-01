"""
nv/subgroups_download.py — Nevada (NDE) Report Card API subgroup assessment data

Extends nv/download.py by adding the `subgroups` parameter to summaryCSV, which
causes the API to return one row per org per demographic group (gender, race/
ethnicity, IEP, EL, FRL) rather than aggregate-only rows.

The NV portal's DI/nevada "Achievement" domain triggers:
  summaryCSV?...&subgroups=gender,ethnicity,iep,lep,frl

Output: data/raw/nv/<dataset>_subgroups/all_years.csv
Manifest: data/raw/nv/subgroups_manifest.csv

Run:
    python scripts/nv/subgroups_download.py
Environment:
    NV_MIN_YEAR=2019   earliest spring year (default)
    NV_MAX_YEAR=2025   latest spring year (default)
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
MANIFEST_PATH = OUT_DIR / "subgroups_manifest.csv"

MIN_YEAR = int(os.environ.get("NV_MIN_YEAR", "2019"))
MAX_YEAR = int(os.environ.get("NV_MAX_YEAR", "2025"))
YEARS = list(range(MIN_YEAR, MAX_YEAR + 1))

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

SUBGROUPS = "gender,ethnicity,iep,lep,frl"

DATASETS = [
    {
        "name": "assessment_sbac_subgroups",
        "code": "e24",
        "grades": [f"g{g}" for g in range(3, 9)],
        "scores": "N_MA,N_RD,N_SC,MA_NotTested,RD_NotTested,MA_Tested,RD_Tested,MA_pass,RD_pass,SC_pass,MA_level,RD_level,SC_level",
    },
    {
        "name": "assessment_ccr_grade11_subgroups",
        "code": "e25",
        "grades": [],
        "scores": "N_MA,N_ELA,MA_NotTested,ELA_NotTested,MA_Tested,ELA_Tested,MA_Pass,ELA_Pass,MA_level,ELA_level",
    },
    {
        "name": "assessment_science_5_8_subgroups",
        "code": "e30",
        "grades": [],
        "scores": "N_SC,SC_NotTested,SC_Tested,SC_pass,SC_level",
    },
    {
        "name": "assessment_science_9_10_subgroups",
        "code": "e29",
        "grades": [],
        "scores": "N,SC_NotTested,SC_Tested,pass,level",
    },
    {
        "name": "assessment_naa_subgroups",
        "code": "e31",
        "grades": [],
        "scores": "MA_EA,RD_EA,SC_EA,MA_level,RD_level,SC_level",
    },
    {
        "name": "assessment_elpa_subgroups",
        "code": "e39",
        "grades": [],
        "scores": "N_Compo,Compo_Tested,Compo_NotTested,Compo_Pro,CO",
    },
]

MANIFEST_FIELDS = [
    "state", "dataset", "year", "scope", "local_path",
    "status", "rows", "size_bytes", "sha256",
]


def get_year_codes(session):
    scopes = session.get(API + "scopes", timeout=30).json()["scopes"]
    return {int(s["value"]): s["code"] for s in scopes if s["type"] == "year"}


def get_collection(session):
    orgs = session.get(API + "organizations", timeout=30).json()
    ids = [str(o["id"]) for o in orgs]
    body = "=" + ",".join(ids)
    r = session.post(API + "organizationcollectionhash", data=body,
                     headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    r.raise_for_status()
    col = r.text.strip().strip('"')
    return (col if col.startswith("c") else "c" + col), len(orgs)


def _pull(session, col_id, ds, year_codes):
    scope_parts = [ds["code"]] + year_codes + ds["grades"]
    scope = ".".join(scope_parts)
    url = (f"{API}summaryCSV?report=summary_1&organization={col_id}"
           f"&scope={scope}&scores={ds['scores']}&subgroups={SUBGROUPS}")
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

    resp = session.get(url, timeout=300)
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
    print(f"  subgroups: {SUBGROUPS}")
    print(f"  datasets: {[d['name'] for d in DATASETS]}")

    manifest = IncrementalManifest(MANIFEST_PATH, MANIFEST_FIELDS)
    saved = 0
    for ds in tqdm.tqdm(DATASETS, desc="NV subgroup datasets"):
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
        time.sleep(1)

    print(f"\nDone. {saved}/{len(DATASETS)} subgroup CSVs. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
