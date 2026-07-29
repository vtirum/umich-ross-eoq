"""
mn/report_card_subgroups.py — Minnesota Report Card data BY DEMOGRAPHIC SUBGROUP

Companion to report_card.py. That script pulls each report for "all students"
(categories=FOC_NONE). The Report Card API also accepts a `categories=<code>`
parameter that returns the same report for a single demographic subgroup, so this
script iterates the valid subgroup codes to capture the race / gender / IEP (special
education) / ELL / FRP breakdowns.

The valid codes per report come from:
    WFServlet?...IBIF_ex=rptcard_getfilter_demographic.fex&reportCode=<code>
grouped as ethnicity (8 race groups), gender (male/female), and specialPop
(EL, specialEd = IEP, FRP, migrant, homeless, ...). Not every report exposes
gender. One getdata call = one subgroup; the response still carries state +
district + school context rows for that subgroup.

Only the reports whose getfilter_demographic returns categories are pulled:
achievement, progress, graduation, attendance, college-going, HS courses,
well-rounded, and staffing. (demographics IS the breakdown; growth/ELP/engagement
expose no subgroups.)

Output:  data/raw/mn/report_card_subgroups/<report>__<level>.jsonl
         one line per (org, subgroup): {orgId, orgName, category, categoryGroup, response}
Manifest: data/raw/mn/report_card_subgroups/manifest.csv

Run:
    python scripts/mn/report_card_subgroups.py
Environment:
    MN_SUB_LEVELS=state          org levels (default "state"; add district,school —
                                 note school-level is ~9 reports x ~14 groups x ~2000
                                 schools and most cells are suppressed)
    MN_YEAR=2024
    MN_SUB_REPORTS=graduation,...  restrict to specific reports
"""

import sys
import os
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from common.manifest import write_csv


def make_session(headers=None):
    """Fail-fast session: the shared client retries 5x with 1.5 backoff, which turns
    one throttled/hung connection into a 5+ minute stall. Here a bad connection
    costs ~1 retry and the per-request timeout, then we move on (recorded, retried
    on a later resume run)."""
    s = requests.Session()
    retry = Retry(total=1, connect=1, read=1, backoff_factor=0.5,
                  status_forcelist=[429, 500, 502, 503, 504], raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    if headers:
        s.headers.update(headers)
    return s


REQUEST_TIMEOUT = 20  # fail fast on a throttled/hung connection

BASE = "https://rc.education.mn.gov/ibi_apps/WFServlet"
APP = "rptcard_reports"
OUT_DIR = Path("data/raw/mn/report_card_subgroups")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

YEAR = os.environ.get("MN_YEAR", "2024")
LEVELS = [x.strip() for x in os.environ.get("MN_SUB_LEVELS", "state").split(",") if x.strip()]
REPORT_FILTER = {x.strip() for x in os.environ.get("MN_SUB_REPORTS", "").split(",") if x.strip()}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Referer": "https://rc.education.mn.gov/",
    "Accept": "application/json, text/plain, */*",
}
STATE_ORG = ("999999000000", "Statewide")

# report name -> (reportCode for the org/category filters, getdata fex, extra params)
REPORTS = [
    {"name": "northstar_achievement", "code": 22, "fex": "rptcard_getdata_northstar_academic_achievement.fex", "extra": {"nscomparisonline": "FOC_NONE"}},
    {"name": "northstar_progress",    "code": 23, "fex": "rptcard_getdata_northstar_academic_progress.fex", "extra": {}},
    {"name": "graduation",            "code": 5,  "fex": "rptcard_getdata_gradrate", "extra": {"graduationYearRate": "4", "nscomparisonline": "FOC_NONE"}},
    {"name": "northstar_attendance",  "code": 15, "fex": "rptcard_getdata_northstar_attendance.fex", "extra": {"nscomparisonline": "FOC_NONE"}},
    {"name": "college_going",         "code": 11, "fex": "rptcard_getdata_collegegoing", "extra": {}},
    {"name": "high_school_courses",   "code": 27, "fex": "rptcard_getdata_HighSchoolCourses.fex", "extra": {}},
    {"name": "well_rounded",          "code": 28, "fex": "rptcard_getdata_WellRoundedEducation.fex", "extra": {}},
    {"name": "staffing",              "code": 8,  "fex": "rptcard_getdata_staff.fex", "extra": {}},
]

MANIFEST_FIELDS = ["state", "report", "group_type", "n_subgroups", "n_records",
                   "n_data", "local_path", "status"]


def _get_categories(session, code):
    """Return [(code, groupCode, displayName)] of subgroup categories for a report."""
    r = session.get(BASE, params={"IBIAPP_app": APP, "IBIF_ex": "rptcard_getfilter_demographic.fex",
                                   "reportCode": code}, timeout=60)
    r.raise_for_status()
    out = []
    for c in r.json():
        # skip "average"/aggregate pseudo-groups; keep real demographic subgroups
        if c.get("code") and c.get("code") != "average":
            out.append((c["code"], c.get("groupCode", ""), c.get("displayName", "")))
    return out


def _get_orglist(session, code):
    r = session.get(BASE, params={"IBIAPP_app": APP, "IBIF_ex": "rptcard_getfilter_orglist.fex",
                                   "reportCode": code}, timeout=60)
    r.raise_for_status()
    j = r.json()
    out = {"district": [], "school": []}
    for oid, meta in (j.get("groups", {}).get("district") or {}).items():
        out["district"].append((oid, (meta or {}).get("name", "")))
    for oid, meta in (j.get("schools") or {}).items():
        out["school"].append((oid, (meta or {}).get("name", "")))
    return out


def _has_data(resp):
    ds = resp.get("dataSets") if isinstance(resp, dict) else None
    if isinstance(ds, dict):
        for v in ds.values():
            d = v.get("data") if isinstance(v, dict) else None
            if (isinstance(d, list) and d) or (isinstance(d, dict) and any(d.values())):
                return True
    return False


def _fetch(session, report, org_id, org_name, group_type, category):
    params = {"IBIAPP_app": APP, "IBIF_ex": report["fex"], "orgName": org_name,
              "orgId": org_id, "groupType": group_type, "year": YEAR, "categories": category}
    params.update(report["extra"])
    r = session.get(BASE, params=params, timeout=REQUEST_TIMEOUT)
    if r.status_code >= 400:
        return {"_status": f"http_{r.status_code}"}
    txt = r.text.strip()
    if not txt.startswith("{"):
        return {"_status": "non_json"}
    try:
        return r.json()
    except ValueError:
        return {"_status": "bad_json"}


def _done_keys(path):
    done = set()
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    done.add((rec["orgId"], rec["category"]))
                except (ValueError, KeyError):
                    continue
    return done


# Long runs against this server degrade if one session is reused for tens of
# thousands of requests (observed ~1s/req -> ~200s/req). Rebuild periodically.
SESSION_REFRESH_EVERY = 1500


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)
    fetch_count = 0
    reports = [r for r in REPORTS if not REPORT_FILTER or r["name"] in REPORT_FILTER]
    manifest = []

    for report in reports:
        cats = _get_categories(session, report["code"])
        if not cats:
            print(f"[{report['name']}] no subgroup categories, skipping")
            continue
        need_orglist = any(l in ("district", "school") for l in LEVELS)
        orglist = _get_orglist(session, report["code"]) if need_orglist else {"district": [], "school": []}

        for group_type in LEVELS:
            orgs = [STATE_ORG] if group_type == "state" else orglist.get(group_type, [])
            if not orgs:
                continue
            out_path = OUT_DIR / f"{report['name']}__{group_type}.jsonl"
            done = _done_keys(out_path)
            n_rec = n_data = 0
            pending = [(o, cat) for o in orgs for cat in cats if (o[0], cat[0]) not in done]
            desc = f"{report['name'][:16]:16s} {group_type:8s} x{len(cats)}grp"

            with open(out_path, "a", encoding="utf-8") as f:
                for (oid, name), (ccode, cgroup, cdisp) in tqdm.tqdm(pending, desc=desc, leave=False):
                    if fetch_count and fetch_count % SESSION_REFRESH_EVERY == 0:
                        session.close()
                        session = make_session(headers=HEADERS)
                    fetch_count += 1
                    try:
                        resp = _fetch(session, report, oid, name, group_type, ccode)
                    except Exception as e:
                        resp = {"_status": f"error:{str(e)[:50]}"}
                    rec = {"orgId": oid, "orgName": name, "groupType": group_type,
                           "report": report["name"], "year": YEAR,
                           "category": ccode, "categoryGroup": cgroup, "categoryName": cdisp,
                           "response": resp}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n_rec += 1
                    if _has_data(resp):
                        n_data += 1
                    time.sleep(0.03)

            # accurate totals from file (resume-safe)
            tot = tot_data = 0
            with open(out_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    tot += 1
                    if _has_data(rec.get("response", {})):
                        tot_data += 1
            print(f"  {report['name']:22s} {group_type:8s}: {len(orgs)} orgs x {len(cats)} groups "
                  f"= {tot} records ({tot_data} with data) -> {out_path.name}")
            manifest.append({"state": "MN", "report": report["name"], "group_type": group_type,
                             "n_subgroups": len(cats), "n_records": tot, "n_data": tot_data,
                             "local_path": str(out_path), "status": "ok"})

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    print(f"\nDone. {len(manifest)} report/level files. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
