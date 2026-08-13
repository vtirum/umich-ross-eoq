"""
Idaho Report Card data files (idahoreportcard.org).

The Data Files page is a Blazor app, but its export is a plain JSON endpoint that
needs no session or token:

    POST /api/DataExport/csv
    {"measures":[4], "breakdowns":[1], "yearIds":[25], "includeAllLevels":true, ...}

The numeric ids are unpublished, so they were recovered by probing the endpoint and
reading the Measure Label / Student Group columns back. That gives 38 measures
(the UI lists 18; the API also carries participation, proficiency bands, targets
and IDAA variants) and 29 breakdowns including Male/Female, which the UI hides in a
nested picker. includeAllLevels returns state, district and school together.

Large selections are refused, so each measure-year is requested separately and the
breakdown list is halved recursively whenever a chunk comes back 400.

Output:   data/raw/id/reportcard/<category>/<measure>__<year>.csv
Env:      ID_YEARS=20,21,22,23,24,25   ID_MEASURES=4,11,15
"""

import os
import sys
import csv
import io
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
import requests

from common.file_utils import sha256_file
from common.manifest import write_csv

URL = "https://www.idahoreportcard.org/api/DataExport/csv"
OUT_DIR = Path("data/raw/id/reportcard")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Content-Type": "application/json",
    "Referer": "https://www.idahoreportcard.org/datafiles",
    "Origin": "https://www.idahoreportcard.org",
}

# measure id -> (slug, category). Ids 89/92/95 duplicate 4/11/15 and are omitted.
MEASURES = {
    3:   ("ela_participation", "assessment"),
    4:   ("ela_proficiency", "assessment"),
    6:   ("ela_proficiency_target", "assessment"),
    7:   ("iri_fall_proficiency", "assessment"),
    8:   ("iri_spring_proficiency", "assessment"),
    10:  ("math_participation", "assessment"),
    11:  ("math_proficiency", "assessment"),
    13:  ("math_proficiency_target", "assessment"),
    14:  ("science_participation", "assessment"),
    15:  ("science_proficiency", "assessment"),
    18:  ("el_progress", "assessment"),
    19:  ("el_progress_target", "assessment"),
    26:  ("grad_4yr", "graduation"),
    28:  ("grad_4yr_target", "graduation"),
    31:  ("ela_growth", "assessment"),
    33:  ("math_growth", "assessment"),
    36:  ("total_enrollment", "enrollment"),
    37:  ("advanced_coursetaking", "graduation"),
    39:  ("advanced_math_8", "assessment"),
    41:  ("advanced_math_9", "assessment"),
    46:  ("chronic_absenteeism", "attendance"),
    90:  ("ela_proficiency_met_goal", "assessment"),
    93:  ("math_proficiency_met_goal", "assessment"),
    115: ("ela_level_below_basic", "assessment"),
    116: ("ela_level_basic", "assessment"),
    117: ("ela_level_proficient", "assessment"),
    118: ("ela_level_advanced", "assessment"),
    119: ("math_level_below_basic", "assessment"),
    120: ("math_level_basic", "assessment"),
    121: ("math_level_proficient", "assessment"),
    122: ("math_level_advanced", "assessment"),
    123: ("science_level_below_basic", "assessment"),
    124: ("science_level_basic", "assessment"),
    125: ("science_level_proficient", "assessment"),
    126: ("science_level_advanced", "assessment"),
    129: ("ela_idaa_participation_not_assessed", "assessment"),
    131: ("math_idaa_participation_not_assessed", "assessment"),
    133: ("science_idaa_participation_not_assessed", "assessment"),
}

# breakdown id -> label (1 = All Students; the rest are student groups)
BREAKDOWNS = {
    1: "All Students",
    18: "American Indian/Alaska Native", 19: "Asian", 20: "Black/African American",
    21: "Hispanic or Latino", 22: "Native Hawaiian/Pacific Islander", 23: "White",
    24: "Multiracial",
    25: "Economically Disadvantaged", 46: "Not Economically Disadvantaged",
    26: "English Learners",
    27: "Students with Disabilities", 48: "Students without Disabilities",
    76: "With Disabilities (Regular)", 77: "With Disabilities (Alternate)",
    78: "With Disabilities (Regular w/ Accommodation)",
    28: "Foster Care", 29: "Homeless", 30: "Migrant Families", 31: "Military Families",
    53: "Male", 54: "Female",
    32: "Grade 3", 33: "Grade 4", 34: "Grade 5", 35: "Grade 6", 36: "Grade 7",
    37: "Grade 8", 38: "High School",
}

YEAR_LABELS = {20: "2019-20", 21: "2020-21", 22: "2021-22",
               23: "2022-23", 24: "2023-24", 25: "2024-25"}

YEARS = [int(y) for y in os.environ.get("ID_YEARS", "20,21,22,23,24,25").split(",")]
MEASURE_FILTER = {int(x) for x in os.environ.get("ID_MEASURES", "").split(",") if x.strip()}

MANIFEST_FIELDS = ["state", "category", "measure_id", "measure", "year", "n_rows",
                   "local_path", "status", "size_bytes", "sha256"]


def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _payload(measure, breakdowns, year):
    return {"measures": [measure], "breakdowns": list(breakdowns), "fileFormat": 0,
            "isNormalized": True, "includeAllLevels": True, "organizationScope": 1,
            "organizationExternalId": None, "yearIds": [year],
            "districtExternalIds": None}


def fetch_chunked(session, measure, breakdowns, year, depth=0):
    """Return CSV text blocks, halving the breakdown list whenever a chunk is refused."""
    def split():
        mid = len(breakdowns) // 2
        return (fetch_chunked(session, measure, breakdowns[:mid], year, depth + 1)
                + fetch_chunked(session, measure, breakdowns[mid:], year, depth + 1))

    try:
        r = session.post(URL, json=_payload(measure, breakdowns, year), timeout=300)
    except Exception:
        return [] if (len(breakdowns) == 1 or depth > 6) else split()
    if r.status_code == 200 and len(r.content) > 80:
        return [r.content.decode("utf-8-sig", "replace")]
    # 400 == "Your selection is too large to export"
    if r.status_code == 400 and len(breakdowns) > 1 and depth <= 6:
        return split()
    return []


def _merge(blocks):
    """Concatenate CSV blocks, keeping a single header row."""
    header, rows = None, []
    for b in blocks:
        rd = csv.reader(io.StringIO(b))
        try:
            h = next(rd)
        except StopIteration:
            continue
        if header is None:
            header = h
        rows.extend(r for r in rd if any(x.strip() for x in r))
    return header, rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = _session()
    measures = {k: v for k, v in MEASURES.items() if not MEASURE_FILTER or k in MEASURE_FILTER}
    bids = list(BREAKDOWNS)

    combos = [(m, y) for m in measures for y in YEARS]
    manifest = []
    for mid, year in tqdm.tqdm(combos, desc="ID report card"):
        slug, cat = measures[mid]
        ylab = YEAR_LABELS.get(year, str(year))
        dest = OUT_DIR / cat / f"{slug}__{ylab}.csv"
        dest.parent.mkdir(parents=True, exist_ok=True)
        row = {"state": "ID", "category": cat, "measure_id": mid, "measure": slug,
               "year": ylab, "n_rows": 0, "local_path": str(dest),
               "status": "", "size_bytes": "", "sha256": ""}
        if dest.exists() and dest.stat().st_size > 0:
            row.update(status="skipped_existing", size_bytes=dest.stat().st_size,
                       sha256=sha256_file(dest))
            manifest.append(row)
            continue
        header, rows = _merge(fetch_chunked(session, mid, bids, year))
        if not rows:
            row["status"] = "no_data"
            manifest.append(row)
            continue
        with open(dest, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if header:
                w.writerow(header)
            w.writerows(rows)
        row.update(status="downloaded", n_rows=len(rows),
                   size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
        manifest.append(row)
        time.sleep(0.2)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    tot = sum(int(r["n_rows"]) for r in manifest if str(r["n_rows"]).isdigit())
    mb = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit()) / 1e6
    print(f"\nDone. {ok}/{len(manifest)} files, {tot:,} rows ({mb:.1f} MB). "
          f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
