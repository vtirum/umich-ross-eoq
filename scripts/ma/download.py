"""
ma/download.py — Massachusetts (DESE) statewide reports

profiles.doe.mass.edu/statereport/<report>.aspx renders each statewide report as
a full HTML data table (all districts or all schools). The year / report-type /
grade / subgroup filters are ASP.NET WebForms postbacks — there is no GET API
and no clean Excel export URL. This script replicates the postback with requests:
GET the page (to grab __VIEWSTATE etc. + the dropdown options), then POST the
desired year + report type, and parse the resulting HTML table into CSV.

Covers every target category:
  mcas / participation / mcas_item  — assessment (MCAS achievement, participation)
  enrollmentbygrade / enrollmentbyracegender / selectedpopulations — enrollment
  teacherbyracegender / teachersalaries / gradesubjectstaffing    — teacher/staff
  ppx                                                              — finance (per-pupil)
  gradrates / dropout                                              — graduation/dropout
  ssdr                                                             — discipline

For each report we pull DISTRICT and SCHOOL levels for each available year, with
grade=ALL and subgroup=All Students (the default rollups).

Run:
    python scripts/ma/download.py
Environment:
    MA_MIN_YEAR=2019   earliest year to pull (default; 0 = all years offered)
"""

import sys
import os
import csv
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import tqdm
from bs4 import BeautifulSoup

from common.http_client import make_session
from common.manifest import write_csv

BASE = "https://profiles.doe.mass.edu/statereport/"
OUT_DIR = Path("data/raw/ma")
MANIFEST_PATH = OUT_DIR / "manifest.csv"
MIN_YEAR = int(os.environ.get("MA_MIN_YEAR", "2019"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

# report slug -> (category, label)
REPORTS = {
    "mcas":                  ("assessment", "MCAS Achievement Results"),
    "participation":         ("assessment", "MCAS Participation"),
    "enrollmentbygrade":     ("enrollment", "Enrollment by Grade"),
    "enrollmentbyracegender":("enrollment", "Enrollment by Race/Gender"),
    "selectedpopulations":   ("enrollment", "Enrollment by Selected Populations"),
    "teacherbyracegender":   ("staff", "Staffing by Race/Ethnicity and Gender"),
    "teachersalaries":       ("staff", "Teacher Salaries"),
    "gradesubjectstaffing":  ("staff", "Teacher by Grade and Subject"),
    "ppx":                   ("finance", "Per Pupil Expenditure"),
    "gradrates":             ("graduation", "Graduation Rates"),
    "dropout":               ("dropout", "Dropout Report"),
    "ssdr":                  ("discipline", "Student Discipline (SSDR)"),
}

MANIFEST_FIELDS = [
    "state", "category", "report", "year", "level",
    "local_path", "status", "rows", "cols",
]


def _form_state(soup):
    """Extract ASP.NET hidden form fields."""
    out = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        el = soup.find("input", {"name": name})
        out[name] = el["value"] if el and el.has_attr("value") else ""
    return out


def _selects(soup):
    """name -> list of (value, text) option tuples for each <select>."""
    out = {}
    for sel in soup.find_all("select"):
        name = sel.get("name")
        if not name:
            continue
        out[name] = [(o.get("value", ""), o.get_text(strip=True)) for o in sel.find_all("option")]
    return out


def _biggest_table(soup):
    tables = soup.find_all("table")
    return max(tables, key=lambda t: len(t.find_all("tr")), default=None) if tables else None


def _table_to_rows(table):
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    return rows


def _save_table(category, report, year, level, rows):
    out_dir = OUT_DIR / category / report
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{report}_{year}_{level}.csv"
    with open(dest, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return dest


def _post_report(session, slug, base_state, selects, year_field, year, rt_field, level):
    """POST the form with a given year + report type; return the data table rows."""
    data = dict(base_state)
    data["__EVENTTARGET"] = year_field
    data["__EVENTARGUMENT"] = ""
    # default every select to its first option, then override year + report type
    for name, opts in selects.items():
        data[name] = opts[0][0] if opts else ""
    data[year_field] = year
    if rt_field:
        data[rt_field] = level
    resp = session.post(BASE + f"{slug}.aspx", data=data, timeout=45)
    if resp.status_code != 200:
        return None, resp.status_code
    table = _biggest_table(BeautifulSoup(resp.text, "html.parser"))
    if not table:
        return None, "no_table"
    rows = _table_to_rows(table)
    return rows, "ok"


def collect_report(session, slug, category, label, manifest):
    try:
        r = session.get(BASE + f"{slug}.aspx", timeout=45)
        r.raise_for_status()
    except Exception as e:
        manifest.append({"state": "MA", "category": category, "report": slug, "year": "",
                         "level": "", "local_path": "", "status": f"get_failed:{str(e)[:40]}",
                         "rows": "", "cols": ""})
        return

    soup = BeautifulSoup(r.text, "html.parser")
    base_state = _form_state(soup)
    selects = _selects(soup)

    year_field = next((n for n in selects if n.endswith("ddYear")), None)
    rt_field = next((n for n in selects if "ReportType" in n), None)
    if not year_field:
        manifest.append({"state": "MA", "category": category, "report": slug, "year": "",
                         "level": "", "local_path": "", "status": "no_year_field",
                         "rows": "", "cols": ""})
        return

    years = [v for v, _ in selects[year_field] if v.isdigit() and int(v) >= MIN_YEAR]

    # Report-type option values vary in case across reports (DISTRICT vs District).
    # Read the real values from the select instead of hardcoding.
    if rt_field:
        levels = [(v, t.lower()) for v, t in selects[rt_field]
                  if t.strip().lower() in ("district", "school")]
    else:
        levels = [("", "district")]

    for year in years:
        for level_value, level_name in levels:
            try:
                rows, status = _post_report(session, slug, base_state, selects,
                                            year_field, year, rt_field, level_value)
                if rows and len(rows) > 1:
                    dest = _save_table(category, slug, year, level_name, rows)
                    manifest.append({"state": "MA", "category": category, "report": slug,
                                     "year": year, "level": level_name,
                                     "local_path": str(dest), "status": "saved",
                                     "rows": len(rows) - 1, "cols": len(rows[0])})
                else:
                    manifest.append({"state": "MA", "category": category, "report": slug,
                                     "year": year, "level": level_name, "local_path": "",
                                     "status": f"empty:{status}", "rows": "", "cols": ""})
            except Exception as e:
                manifest.append({"state": "MA", "category": category, "report": slug,
                                 "year": year, "level": level_name, "local_path": "",
                                 "status": f"error:{str(e)[:40]}", "rows": "", "cols": ""})
            time.sleep(0.4)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)

    print(f"MA DESE statewide reports: {len(REPORTS)} reports, years >= {MIN_YEAR}")
    manifest = []
    for slug, (category, label) in tqdm.tqdm(REPORTS.items(), desc="MA reports"):
        collect_report(session, slug, category, label, manifest)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    saved = sum(1 for r in manifest if r["status"] == "saved")
    total_rows = sum(int(r["rows"]) for r in manifest if str(r["rows"]).isdigit())
    print(f"\nDone. {saved} tables saved ({total_rows:,} data rows). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
