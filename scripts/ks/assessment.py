"""
Kansas assessment results (ksreportcard.ksde.gov).

The Data Central report generator (ks/download.py) has 19 reports but none of them
are test scores - Kansas publishes assessment separately, on the Building Report
Card. Two sources there, and they are complementary:

1. Annual full files - the complete dataset, one workbook per school year:

       https://ksreportcard.ksde.gov/<YYYY>_<YYYY+1>_Assessment_Full_File.xlsx

   Each holds every level in one table (state, district AND building), all grades,
   subjects and student subgroups - ~300k rows per file. Linked from the page as
   "Download Full Results". This is the primary source; 2014-15 through 2024-25
   are published.

2. getPerfChart2016 service - the same measures at state and district level, but
   it also returns COUNTS (total tested, students at each level) which the full
   files omit; those carry percentages only. Pulled as a supplement.

       GET /services/dataService.svc/getPerfChart2016
           ?orgNo=State|D0101&bldgNo=0&subj=1&group=1&grade=18&progYear=0&pop=1

Student subgroups cover race, free/reduced lunch, disability, English learner,
homeless, military and foster care - but not gender. Kansas publishes gender only
on the graduation side (see ks/download.py report 12).

KSDE serves an incomplete certificate chain, so verification is disabled here
(public data, no credentials).

Output:   data/raw/ks/assessment/full_files/<year>_Assessment_Full_File.xlsx
          data/raw/ks/assessment/<subject>__<level>__<grade>.csv   (counts supplement)
Manifest: data/raw/ks/assessment/manifest.csv

Env:
    KS_ASSESS_FULL=1                        download the annual full files (default 1)
    KS_ASSESS_API=1                         also pull the counts supplement (default 1)
    KS_ASSESS_YEARS=0,2020,2018,2016,2014   API year anchors (default 0 = last 5 years)
    KS_ASSESS_LEVELS=state,district         API org levels
    KS_ASSESS_GRADES=18                     API district-level grades
"""

import csv
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
import requests
import urllib3

from common.http_client import BROWSER_UA
from common.file_utils import sha256_file
from common.manifest import merge_csv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://ksreportcard.ksde.gov"
SERVICE = f"{BASE}/services/dataService.svc/getPerfChart2016"
ORG_PAGE = f"{BASE}/assessment_results.aspx?org_no=State&rptType=3"
OUT_DIR = Path("data/raw/ks/assessment")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

HEADERS = {"User-Agent": BROWSER_UA, "Referer": ORG_PAGE}

SUBJECTS = {"0": "ela", "1": "math", "2": "science", "3": "history_government"}
GRADES = {"18": "all_grades", "8": "grade3", "9": "grade4", "10": "grade5",
          "11": "grade6", "12": "grade7", "13": "grade8", "15": "high_school"}
GROUPS = {
    "1": "All Students", "2": "Free and Reduced Lunch", "3": "Students with Disabilities",
    "4": "ELL Students", "5": "African-American", "6": "Hispanic", "7": "White",
    "8": "Asian", "9": "American Indian or Alaska Native", "10": "Multi-Racial",
    "14": "Self-Paid Lunch only", "15": "Free Lunch only", "19": "Reduced Lunch only",
    "36": "Native Hawaiian or Pacific Islander", "37": "Not Disabled", "39": "Homeless",
    "40": "ELL with Disabilities", "41": "Non-ELL Students", "42": "Military Connected",
    "43": "Foster Care",
}

FULL_FILE_YEARS = list(range(2014, 2025))       # 2014-15 .. 2024-25
FULL_DIR = OUT_DIR / "full_files"
DO_FULL = os.environ.get("KS_ASSESS_FULL", "1") != "0"
DO_API = os.environ.get("KS_ASSESS_API", "1") != "0"

YEAR_ANCHORS = [y.strip() for y in os.environ.get("KS_ASSESS_YEARS", "0").split(",") if y.strip()]
LEVELS = [x.strip() for x in os.environ.get("KS_ASSESS_LEVELS", "state,district").split(",") if x.strip()]
DISTRICT_GRADES = [g.strip() for g in os.environ.get("KS_ASSESS_GRADES", "18").split(",") if g.strip()]

MANIFEST_FIELDS = ["state", "subject", "level", "grade", "n_rows",
                   "local_path", "status", "size_bytes", "sha256"]

FIELDS = ["org_no", "org_name", "level", "subject", "grade", "student_group",
          "program_year", "orglevel", "total_tested",
          "pct_level_1", "pct_level_2", "pct_level_3", "pct_level_4", "pct_not_tested",
          "n_level_1", "n_level_2", "n_level_3", "n_level_4", "n_not_valid"]


def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = False       # incomplete chain on KSDE hosts
    return s


def get_orgs(session):
    """Return [(org_no, name)] for the state plus every district."""
    r = session.get(ORG_PAGE, timeout=60)
    r.raise_for_status()
    m = re.search(r'id="ddlOrg".*?</select>', r.text, re.S)
    orgs = [("State", "State")]
    if m:
        for val, txt in re.findall(r'value="([^"]*)"[^>]*>([^<]*)<', m.group(0)):
            if val.startswith("D"):
                orgs.append((val, txt.strip()))
    return orgs


def fetch(session, org_no, subj, group, grade, year):
    params = {"orgNo": org_no, "bldgNo": "0", "subj": subj, "group": group,
              "grade": grade, "progYear": year, "pop": "1"}
    try:
        r = session.get(SERVICE, params=params, timeout=60)
        if r.status_code != 200:
            return []
        payload = r.json().get("d")
        return json.loads(payload) if payload else []
    except Exception:
        return []


def _rows(records, org_no, org_name, level, subject, grade, group_label):
    out = []
    for rec in records:
        # district calls also return the statewide comparison series; keep only
        # the rows belonging to this organisation
        label = str(rec.get("orglevel", ""))
        if level == "district" and label.lower().startswith("state"):
            continue
        out.append({
            "org_no": org_no, "org_name": org_name, "level": level,
            "subject": subject, "grade": grade, "student_group": group_label,
            "program_year": rec.get("Program_Year", ""), "orglevel": label,
            "total_tested": rec.get("Total", ""),
            "pct_level_1": rec.get("PCLevel_One", ""), "pct_level_2": rec.get("PCLevel_Two", ""),
            "pct_level_3": rec.get("PCLevel_Three", ""), "pct_level_4": rec.get("PCLevel_Four", ""),
            "pct_not_tested": rec.get("PCNotTested", ""),
            "n_level_1": rec.get("TotalLevel_One", ""), "n_level_2": rec.get("TotalLevel_Two", ""),
            "n_level_3": rec.get("TotalLevel_Three", ""), "n_level_4": rec.get("TotalLevel_Four", ""),
            "n_not_valid": rec.get("TotalLevel_NotValid", ""),
        })
    return out


def download_full_files(session):
    """Fetch the annual full workbooks - every level, grade, subject and subgroup."""
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for y in tqdm.tqdm(FULL_FILE_YEARS, desc="KS full files"):
        name = f"{y}_{y+1}_Assessment_Full_File.xlsx"
        dest = FULL_DIR / name
        row = {"state": "KS", "subject": "all", "level": "state_district_building",
               "grade": "all", "n_rows": 0, "local_path": str(dest),
               "status": "", "size_bytes": "", "sha256": ""}
        if dest.exists() and dest.stat().st_size > 0:
            row.update(status="skipped_existing", size_bytes=dest.stat().st_size,
                       sha256=sha256_file(dest))
            rows.append(row)
            continue
        try:
            r = session.get(f"{BASE}/{name}", timeout=600, stream=True)
            if r.status_code != 200:
                row["status"] = f"http_{r.status_code}"
                rows.append(row)
                continue
            with open(dest, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        fh.write(chunk)
        except Exception as e:
            if dest.exists():
                dest.unlink()
            row["status"] = f"error:{str(e)[:60]}"
            rows.append(row)
            continue
        if dest.stat().st_size < 4096:     # an error page, not a workbook
            dest.unlink()
            row["status"] = "too_small"
        else:
            row.update(status="downloaded", size_bytes=dest.stat().st_size,
                       sha256=sha256_file(dest))
            tqdm.tqdm.write(f"  {name}: {dest.stat().st_size/1e6:.1f} MB")
        rows.append(row)
    return rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = _session()

    manifest_full = download_full_files(session) if DO_FULL else []
    if not DO_API:
        merge_csv(MANIFEST_PATH, manifest_full, MANIFEST_FIELDS, "local_path")
        ok = sum(1 for r in manifest_full if r["status"] in ("downloaded", "skipped_existing"))
        mb = sum(int(r["size_bytes"]) for r in manifest_full if str(r["size_bytes"]).isdigit()) / 1e6
        print(f"\nDone. {ok}/{len(manifest_full)} full files ({mb:.1f} MB). Manifest: {MANIFEST_PATH}")
        return

    orgs = get_orgs(session)
    print(f"{len(orgs)} organisations (state + {len(orgs)-1} districts)")

    # state level gets every grade; districts default to All Grades to keep the
    # request count sane (each extra grade multiplies the run by ~8)
    plan = []
    for subj_id, subj in SUBJECTS.items():
        if "state" in LEVELS:
            for g_id in GRADES:
                plan.append((subj_id, subj, "state", g_id, [("State", "State")]))
        if "district" in LEVELS:
            for g_id in DISTRICT_GRADES:
                plan.append((subj_id, subj, "district", g_id,
                             [o for o in orgs if o[0] != "State"]))

    manifest = list(manifest_full)
    for subj_id, subj, level, g_id, org_list in plan:
        grade = GRADES.get(g_id, g_id)
        dest = OUT_DIR / f"{subj}__{level}__{grade}.csv"
        row = {"state": "KS", "subject": subj, "level": level, "grade": grade,
               "n_rows": 0, "local_path": str(dest), "status": "",
               "size_bytes": "", "sha256": ""}
        if dest.exists() and dest.stat().st_size > 0:
            row.update(status="skipped_existing", size_bytes=dest.stat().st_size,
                       sha256=sha256_file(dest))
            manifest.append(row)
            continue

        combos = [(o, grp, yr) for o in org_list for grp in GROUPS for yr in YEAR_ANCHORS]
        rows = []
        desc = f"{subj[:12]:12s} {level:8s} {grade[:10]:10s}"
        for (org_no, org_name), grp, yr in tqdm.tqdm(combos, desc=desc, leave=False):
            recs = fetch(session, org_no, subj_id, grp, g_id, yr)
            if recs:
                rows.extend(_rows(recs, org_no, org_name, level, subj, grade, GROUPS[grp]))
            time.sleep(0.02)

        if not rows:
            row["status"] = "no_data"
            manifest.append(row)
            continue
        with open(dest, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        row.update(status="downloaded", n_rows=len(rows),
                   size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
        manifest.append(row)
        print(f"  {dest.name}: {len(rows):,} rows")

    # merge so a scoped run does not discard other slices already on disk
    manifest = merge_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS, "local_path")
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    tot = sum(int(r["n_rows"]) for r in manifest if str(r["n_rows"]).isdigit())
    print(f"\nDone. {ok}/{len(manifest)} files, {tot:,} rows. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
