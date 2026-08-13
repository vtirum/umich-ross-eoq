"""
Kansas KSDE Data Central report generator.

There is no JSON API. report_gen.aspx is ASP.NET WebForms, but its final submit
does not render a page: it replies with Content-Type application/vnd.ms-excel and
an attachment, so the generator is itself the download endpoint. We replicate the
postback chain with requests (report -> data_group -> year + btn_Run_Rpt) and keep
the response body as .xls.

19 reports, most already broken out by race/ethnicity, plus graduates by race and
gender, FRL, IDEA/gifted, suspension/expulsion and personnel. Entity levels come
from dd_data_group; we use the three that return every entity in one request
(state, all districts, all counties) rather than the single-entity options.

Two things to know: KSDE serves an incomplete certificate chain, so verification
is disabled for this host (public data, no credentials). And several reports are
historical-only (NCES <=2008, NCLB 2009, suspension and crime 1996-2017), so the
default year window covers the whole archive rather than recent years.

Output:   data/raw/ks/<category>/<report>__<level>__<year>.xls
Env:      KS_YEARS=2019-2025, KS_REPORTS=13,7,8
"""

import os
import sys
import csv
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
import requests
import urllib3
from bs4 import BeautifulSoup

from common.file_utils import sha256_file
from common.manifest import write_csv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL = "https://datacentral.ksde.gov/report_gen.aspx"
OUT_DIR = Path("data/raw/ks")
MANIFEST_PATH = OUT_DIR / "manifest.csv"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")}

# report id -> (slug, category)
REPORTS = {
    "1":  ("attendance_rate_by_type_race", "attendance"),
    "7":  ("dropout_rate_by_race", "graduation"),
    "8":  ("grad_rate_4yr_cohort_by_race", "graduation"),
    "9":  ("grad_rate_5yr_cohort_by_race", "graduation"),
    "10": ("grad_rate_nces_by_race", "graduation"),
    "11": ("grad_rate_nclb_by_race", "graduation"),
    "12": ("graduates_by_postgrad_plans_race_gender", "graduation"),
    "13": ("headcount_enrollment_by_grade_race", "enrollment"),
    "18": ("free_reduced_lunch_headcount", "enrollment"),
    "21": ("idea_and_gifted_totals", "enrollment"),
    "5":  ("concurrent_hs_enrollment", "enrollment"),
    "19": ("suspension_expulsion_counts", "discipline"),
    "14": ("suspension_expulsion_incidents", "discipline"),
    "6":  ("crime_matrix_historical", "discipline"),
    "4":  ("personnel_licensed", "staff"),
    "16": ("personnel_nonlicensed", "staff"),
    "17": ("school_building_program_counts", "directory"),
    "2":  ("building_dates_of_construction", "directory"),
    "15": ("inclement_weather_inservice_dates", "other"),
}

# entity levels that return every entity in a single request
LEVELS = {"1": "state", "3": "district", "8": "county"}

# Several reports are explicitly historical and hold nothing in recent years
# ("NCES Formula - 2008 and Earlier", "NCLB Formula - 2009 Only", suspension/expulsion
# and crime matrix "Historical (…-2017)"), so the default window spans the whole
# archive rather than just recent years. Combinations with no data are recorded as
# `no_data` in the manifest and cost one request each.
YEARS_SPEC = os.environ.get("KS_YEARS", "2002-2025")
REPORT_FILTER = {x.strip() for x in os.environ.get("KS_REPORTS", "").split(",") if x.strip()}

MANIFEST_FIELDS = ["state", "category", "report", "level", "year",
                   "local_path", "status", "size_bytes", "sha256"]


def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = False          # incomplete chain on KSDE's host; see module docstring
    return s


def _form_state(soup):
    """Hidden ASP.NET fields that must be echoed back on every POST."""
    return {i["name"]: i.get("value", "")
            for i in soup.select("input[type=hidden][name]") if i.get("name")}


def _control(soup, fragment):
    el = soup.select_one(f'select[name*="{fragment}"]')
    return el.get("name") if el else None


def fetch_report(session, report_id, level_id, year):
    """Drive the postback chain and return the report as raw bytes.

    The final POST does not render a page — KSDE answers with
    `Content-Type: application/vnd.ms-excel` and an attachment named
    `%%_Reports.xls`, i.e. the generator *is* the download endpoint. So we keep the
    response body verbatim rather than scraping a table out of HTML.
    """
    r = session.get(URL, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    rep_ctl = _control(soup, "ddReports")
    if not rep_ctl:
        return None

    # 1) choose the report — this postback rebuilds the dependent dropdowns
    data = _form_state(soup)
    data.update({"__EVENTTARGET": rep_ctl, "__EVENTARGUMENT": "", rep_ctl: report_id})
    r = session.post(URL, data=data, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")

    grp_ctl = _control(soup, "dd_data_group")
    yr_ctl = _control(soup, "dd_School_Year")
    typ_ctl = _control(soup, "dd_School_Type")

    # 2) choose the entity level (another postback — it can reveal county/district pickers)
    if grp_ctl:
        data = _form_state(soup)
        data.update({"__EVENTTARGET": grp_ctl, "__EVENTARGUMENT": "",
                     rep_ctl: report_id, grp_ctl: level_id})
        if typ_ctl:
            data[typ_ctl] = "%"        # all schools
        r = session.post(URL, data=data, timeout=60)
        soup = BeautifulSoup(r.text, "html.parser")
        yr_ctl = _control(soup, "dd_School_Year") or yr_ctl
        typ_ctl = _control(soup, "dd_School_Type") or typ_ctl

    # 3) submit with the year selected
    btn = soup.select_one("input[id*=btn_Run_Rpt]")
    data = _form_state(soup)
    data[rep_ctl] = report_id
    if grp_ctl:
        data[grp_ctl] = level_id
    if typ_ctl:
        data[typ_ctl] = "%"
    if yr_ctl:
        data[yr_ctl] = str(year)
    if btn and btn.get("name"):
        data[btn["name"]] = btn.get("value", "Display Report")
    r = session.post(URL, data=data, timeout=120)
    ct = r.headers.get("Content-Type", "").lower()
    body = r.content
    # a real report comes back as an OLE2 (.xls) or zip (.xlsx) payload; anything
    # else means the combination produced no report
    if "excel" in ct or "spreadsheet" in ct or body[:4] in (b"\xd0\xcf\x11\xe0", b"PK\x03\x04"):
        return body
    return None


def main():
    a, b = YEARS_SPEC.split("-")
    years = list(range(int(a), int(b) + 1))
    reports = {k: v for k, v in REPORTS.items() if not REPORT_FILTER or k in REPORT_FILTER}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = _session()

    combos = [(rid, lid, yr) for rid in reports for lid in LEVELS for yr in years]
    manifest = []
    for rid, lid, yr in tqdm.tqdm(combos, desc="KS reports"):
        slug, cat = reports[rid]
        level = LEVELS[lid]
        dest = OUT_DIR / cat / f"{slug}__{level}__{yr}.xls"
        dest.parent.mkdir(parents=True, exist_ok=True)
        row = {"state": "KS", "category": cat, "report": slug, "level": level,
               "year": yr, "local_path": str(dest),
               "status": "", "size_bytes": "", "sha256": ""}
        if dest.exists() and dest.stat().st_size > 0:
            row.update(status="skipped_existing", size_bytes=dest.stat().st_size,
                       sha256=sha256_file(dest))
            manifest.append(row)
            continue
        try:
            body = fetch_report(session, rid, lid, yr)
        except Exception as e:
            row["status"] = f"error:{str(e)[:60]}"
            manifest.append(row)
            continue
        if not body or len(body) < 4096:
            row["status"] = "no_data"
            manifest.append(row)
            continue
        dest.write_bytes(body)
        row.update(status="downloaded", size_bytes=dest.stat().st_size,
                   sha256=sha256_file(dest))
        manifest.append(row)
        time.sleep(0.3)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    mb = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit()) / 1e6
    print(f"\nDone. {ok}/{len(manifest)} report-files ({mb:.1f} MB). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
