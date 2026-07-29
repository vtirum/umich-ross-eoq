"""
mn/report_card.py — Minnesota Report Card (rc.education.mn.gov) WebFOCUS API

Minnesota publishes school/district data through the Minnesota Report Card, a
single-page app backed by a WebFOCUS reporting server. There is no bulk file
download; data is served per organization as JSON from:

    https://rc.education.mn.gov/ibi_apps/WFServlet
        ?IBIAPP_app=rptcard_reports
        &IBIF_ex=rptcard_getdata_<report>
        &orgName=<name>&orgId=<id>&groupType=state|district|school
        &year=<YYYY>[&report-specific params]

Each response bundles the requested year's detail plus a multi-year trend, so one
call per org per report captures recent history. The statewide org is 999999000000.

This script pulls the reports that resolve from just (org, year) — covering
assessment (North Star achievement/progress, MN Growth, NAEP), enrollment
(demographics), graduation, staffing, finance (fiscal transparency), plus English
learners, college-going, early childhood, HS courses, and well-rounded education.

Not yet included (need extra dimensional params / form interaction; tracked as
follow-ups): detailed MCA-by-test/subject/grade (stateassessments), ACCESS by
test/grade, and the discipline sub-reports (suspensions/expulsions/violence/
referrals). Discipline is covered for MN by the federal CRDC pull (scripts/crdc).

The MDE Analytics site (pub.education.mn.gov) is a separate, Perfdrive/hCaptcha-
gated WebFOCUS shell and is not used here — the Report Card API is the clean
structured source. rc.education.mn.gov itself is not bot-gated.

Output:  data/raw/mn/report_card/<report>__<groupType>.jsonl   (one org per line)
Manifest: data/raw/mn/report_card/manifest.csv

Run:
    python scripts/mn/report_card.py
Environment:
    MN_YEAR=2024          analysis year to request (default 2024 = last fully-published
                          year, covers every report; a 5-year trend is embedded in each
                          response regardless. Use MN_YEAR=2025 for reports already
                          reporting 2024-25, e.g. graduation/demographics/northstar.)
    MN_LEVELS=state,district,school   which org levels to pull (default all three)
    MN_REPORTS=graduation,demographics,...   restrict to specific reports (default all)
"""

import sys
import os
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm

from common.http_client import make_session
from common.manifest import write_csv

BASE = "https://rc.education.mn.gov/ibi_apps/WFServlet"
APP = "rptcard_reports"
OUT_DIR = Path("data/raw/mn/report_card")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

YEAR = os.environ.get("MN_YEAR", "2024")
LEVELS = [x.strip() for x in os.environ.get("MN_LEVELS", "state,district,school").split(",") if x.strip()]
REPORT_FILTER = {x.strip() for x in os.environ.get("MN_REPORTS", "").split(",") if x.strip()}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Referer": "https://rc.education.mn.gov/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

STATE_ORG = ("999999000000", "Statewide")

# report url-slug, WebFOCUS getdata procedure, and any extra fixed params.
# reportCode is used only to fetch each report's own org list.
REPORTS = [
    {"name": "graduation",           "code": 5,  "fex": "rptcard_getdata_gradrate",
     "extra": {"graduationYearRate": "4", "nscomparisonline": "FOC_NONE"}},
    {"name": "demographics",         "code": 6,  "fex": "rptcard_getdata_demographics.fex", "extra": {}},
    {"name": "staffing",             "code": 8,  "fex": "rptcard_getdata_staff.fex", "extra": {}},
    {"name": "well_rounded",         "code": 28, "fex": "rptcard_getdata_WellRoundedEducation.fex", "extra": {}},
    {"name": "high_school_courses",  "code": 27, "fex": "rptcard_getdata_HighSchoolCourses.fex", "extra": {}},
    {"name": "my_school",            "code": 9,  "fex": "rptcard_getdata_myschool", "extra": {}},
    {"name": "college_going",        "code": 11, "fex": "rptcard_getdata_collegegoing", "extra": {}},
    {"name": "northstar_attendance", "code": 15, "fex": "rptcard_getdata_northstar_attendance.fex",
     "extra": {"nscomparisonline": "FOC_NONE"}},
    {"name": "preschool",            "code": 20, "fex": "rptcard_getdata_preschool", "extra": {}},
    {"name": "northstar_achievement","code": 22, "fex": "rptcard_getdata_northstar_academic_achievement.fex",
     "extra": {"nscomparisonline": "FOC_NONE"}},
    {"name": "northstar_progress",   "code": 23, "fex": "rptcard_getdata_northstar_academic_progress.fex", "extra": {}},
    {"name": "northstar_elp",        "code": 24, "fex": "rptcard_getdata_northstar_elp.fex",
     "extra": {"nscomparisonline": "FOC_NONE"}},
    {"name": "fiscal_transparency",  "code": 26, "fex": "rptcard_getdata_fiscal", "extra": {}},
    {"name": "head_start",           "code": 21, "fex": "rptcard_getdata_headstart.fex", "extra": {}},
    {"name": "mn_growth",            "code": 3,  "fex": "rptcard_getdata_mngrowth.fex", "extra": {}},
    {"name": "naep",                 "code": 10, "fex": "rptcard_getdata_naep.fex", "extra": {}},
]

MANIFEST_FIELDS = ["state", "report", "group_type", "n_orgs", "n_data", "n_empty", "local_path", "status"]


def _get_orglist(session, code):
    """Return {'district': [(id,name)], 'school': [(id,name)]} for a report code."""
    params = {"IBIAPP_app": APP, "IBIF_ex": "rptcard_getfilter_orglist.fex", "reportCode": code}
    r = session.get(BASE, params=params, timeout=60)
    r.raise_for_status()
    j = r.json()
    out = {"district": [], "school": []}
    groups = j.get("groups", {})
    for oid, meta in (groups.get("district") or {}).items():
        out["district"].append((oid, (meta or {}).get("name", "")))
    for oid, meta in (j.get("schools") or {}).items():
        out["school"].append((oid, (meta or {}).get("name", "")))
    return out


def _fetch(session, report, org_id, org_name, group_type):
    params = {
        "IBIAPP_app": APP, "IBIF_ex": report["fex"],
        "orgName": org_name, "orgId": org_id, "groupType": group_type, "year": YEAR,
    }
    params.update(report["extra"])
    r = session.get(BASE, params=params, timeout=60)
    if r.status_code >= 400:
        return {"_status": f"http_{r.status_code}"}
    txt = r.text.strip()
    if not txt.startswith("{"):
        return {"_status": "non_json"}
    try:
        return r.json()
    except ValueError:
        return {"_status": "bad_json"}


def _has_data(resp):
    """True if the response carries any non-empty dataSet."""
    ds = resp.get("dataSets")
    if isinstance(ds, dict):
        for v in ds.values():
            d = v.get("data") if isinstance(v, dict) else None
            if isinstance(d, list) and d:
                return True
            if isinstance(d, dict) and any(d.values()):
                return True
    return False


def _count_data(path):
    """Return (n_with_data, n_total) by scanning a completed jsonl file."""
    data = total = 0
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                total += 1
                if _has_data(rec.get("response", {})):
                    data += 1
    return data, total


def _done_org_ids(path):
    """Read already-saved orgIds from a jsonl file so reruns resume."""
    done = set()
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["orgId"])
                except (ValueError, KeyError):
                    continue
    return done


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)

    reports = [r for r in REPORTS if not REPORT_FILTER or r["name"] in REPORT_FILTER]
    manifest = []

    for report in reports:
        # org lists are per-report; state level needs no list
        try:
            orglist = _get_orglist(session, report["code"]) if ("district" in LEVELS or "school" in LEVELS) else {"district": [], "school": []}
        except Exception as e:
            print(f"[{report['name']}] orglist error: {str(e)[:80]}")
            orglist = {"district": [], "school": []}

        for group_type in LEVELS:
            if group_type == "state":
                orgs = [STATE_ORG]
            else:
                orgs = orglist.get(group_type, [])
            if not orgs:
                continue

            out_path = OUT_DIR / f"{report['name']}__{group_type}.jsonl"
            done = _done_org_ids(out_path)
            n_data = n_empty = 0
            pending = [(oid, name) for oid, name in orgs if oid not in done]
            desc = f"{report['name'][:18]:18s} {group_type:8s}"

            with open(out_path, "a", encoding="utf-8") as f:
                for oid, name in tqdm.tqdm(pending, desc=desc, leave=False):
                    try:
                        resp = _fetch(session, report, oid, name, group_type)
                    except Exception as e:
                        resp = {"_status": f"error:{str(e)[:50]}"}
                    rec = {"orgId": oid, "orgName": name, "groupType": group_type,
                           "report": report["name"], "year": YEAR, "response": resp}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    if _has_data(resp):
                        n_data += 1
                    else:
                        n_empty += 1
                    time.sleep(0.05)

            total = len(orgs)
            # Count data/empty from the whole file so the manifest is accurate on
            # resumed runs (orgs skipped this run are still real records on disk).
            file_data, file_total = _count_data(out_path)
            print(f"  {report['name']:22s} {group_type:8s}: {file_total}/{total} orgs on disk "
                  f"({file_data} with data; {n_data} fetched this run) -> {out_path.name}")
            manifest.append({
                "state": "MN", "report": report["name"], "group_type": group_type,
                "n_orgs": total, "n_data": file_data, "n_empty": file_total - file_data,
                "local_path": str(out_path), "status": "ok",
            })

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    print(f"\nDone. {len(manifest)} report/level files. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
