"""
mi/dashboard_scrape.py — Michigan current-data dashboard scraper (mischooldata.org)

The "current" enrollment, graduation/dropout, and M-STEP assessment data on
mischooldata.org is served by a legacy ASP.NET WebForms app embedded as an
iframe (legacy.mischooldata.org/DistrictSchoolProfiles2/...). The results
render as plain tab-separated tables in the rendered page text, so this script
drives a headless browser, loads one URL per (report tool, school year, [grade,
subject]) combination at the Statewide level, and extracts every tab-separated
table from the rendered text.

Tools covered (Statewide, all available years):
  - Student Enrollment Counts (StudentCount.aspx)
  - Graduation/Dropout Rate    (GraduationDropoutRate3.aspx)
  - Grades 3-8 M-STEP Performance (AssessmentGradesPerformance2.aspx), by grade x subject

Run:
    python scripts/mi/dashboard_scrape.py
"""

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

OUT_DIR = Path("data/raw/mi/dashboard")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

STATEWIDE = "1-A,0,0,0~2-A,0,0,0"

# legacy school-year codes -> label, from RequestStudentFactSchoolYearItems2
SCHOOL_YEARS = {
    1: "2002-03", 2: "2003-04", 3: "2004-05", 4: "2005-06", 5: "2006-07",
    6: "2007-08", 8: "2008-09", 9: "2009-10", 10: "2010-11", 11: "2011-12",
    12: "2012-13", 13: "2013-14", 14: "2014-15", 15: "2015-16", 18: "2016-17",
    19: "2017-18", 20: "2018-19", 21: "2019-20", 22: "2020-21", 23: "2021-22",
    24: "2022-23", 25: "2023-24", 26: "2024-25", 27: "2025-26",
}

ASSESSMENT_YEARS = [15, 18, 19, 22, 23, 24, 25, 26, 27]  # M-STEP era (skip 21=2019-20, no spring 2020 test)
GRADES = [f"Grade{n:02d}" for n in range(3, 9)]
SUBJECTS = ["Ela", "Math"]


def extract_tables(text):
    """Find tab-separated tables in rendered page text: a header line (>=3
    tab-separated cells) followed by one or more data lines with the same
    number of cells."""
    lines = text.split("\n")
    tables = []
    i = 0
    while i < len(lines):
        cols = lines[i].split("\t")
        if len(cols) >= 3:
            header = cols
            data = []
            j = i + 1
            while j < len(lines):
                next_cols = lines[j].split("\t")
                if len(next_cols) != len(cols) or next_cols == header:
                    break
                data.append(next_cols)
                j += 1
            if data:
                tables.append((header, data))
            i = j
        else:
            i += 1
    return tables


def fetch(page, url, wait_ms=12000):
    page.goto(url, timeout=60000)
    page.wait_for_timeout(wait_ms)
    for f in page.frames:
        if "legacy.mischooldata" in f.url:
            try:
                return f.evaluate("document.body.innerText")
            except Exception:
                return ""
    return ""


def write_rows(out_path, fieldnames, rows):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out_path.exists()
    with open(out_path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new_file and fieldnames is not None:
            w.writerow(fieldnames)
        for r in rows:
            w.writerow(r)


def scrape_enrollment(page):
    print("== Enrollment counts (Statewide, all years) ==")
    out = OUT_DIR / "enrollment_counts_statewide.csv"
    if out.exists():
        out.unlink()
    header_out = None
    for code, label in SCHOOL_YEARS.items():
        url = (
            "https://www.mischooldata.org/student-enrollment-counts-report"
            f"?Common_Locations={STATEWIDE}&Common_SchoolYear={code}"
            "&Common_LocationIncludeComparison=False&Portal_InquiryDisplayType=Snapshot"
            "&Common_Subgroup_StudentCountFact2=AllStudents&Common_Grade=AllGrades&Common_CrossTab=None"
        )
        text = fetch(page, url)
        tables = extract_tables(text)
        rows = []
        for header, data in tables:
            if header[:1] == ["Location Name"] and "School Year" in header:
                if header_out is None:
                    header_out = header + ["query_school_year"]
                for d in data:
                    rows.append(d + [label])
                break
        if rows:
            if not out.exists():
                write_rows(out, header_out, rows)
            else:
                write_rows(out, None, rows)
        print(f"  {label}: {len(rows)} rows")


def scrape_graddropout(page):
    print("== Graduation/Dropout rate (Statewide, all years) ==")
    out = OUT_DIR / "graddropout_statewide.csv"
    if out.exists():
        out.unlink()
    for code, label in SCHOOL_YEARS.items():
        if code < 12:  # cohort rates only meaningful from ~2013-14 onward
            continue
        url = (
            "https://www.mischooldata.org/graddropout-rate"
            f"?Common_Locations={STATEWIDE}&Common_SchoolYear={code}"
            "&Common_LocationIncludeComparison=False&Portal_InquiryDisplayType=Snapshot"
            "&Common_Subgroup_GraduationDropout3=AllStudents&Portal_Cohort=AllYears&Common_CrossTab=None"
        )
        text = fetch(page, url)
        tables = extract_tables(text)
        rows = []
        header_out = None
        for header, data in tables:
            if header[:1] == ["Location Name"] and "Cohort Graduation Year" in header:
                header_out = header
                for d in data:
                    rows.append(d + [label])
                break
        if rows:
            if not out.exists():
                write_rows(out, header_out + ["query_school_year"], rows)
            else:
                write_rows(out, None, rows)
        print(f"  {label}: {len(rows)} rows")


def scrape_assessment(page):
    print("== Grades 3-8 M-STEP performance (Statewide, by year/grade/subject) ==")
    out = OUT_DIR / "assessment_mstep_statewide.csv"
    if out.exists():
        out.unlink()
    header_out = None
    for code in ASSESSMENT_YEARS:
        label = SCHOOL_YEARS[code]
        for grade in GRADES:
            for subject in SUBJECTS:
                url = (
                    "https://www.mischooldata.org/grades-3-8-state-testing-includes-psat-data-performance"
                    f"?Common_Locations={STATEWIDE}&Common_SchoolYear={code}"
                    "&Common_LocationIncludeComparison=False&Portal_InquiryDisplayType=Snapshot"
                    f"&Common_Grade={grade}&Common_Subject={subject}&Common_AssessmentType=None"
                    "&Common_AssessmentProgram=Mstep&Common_TestingGroup=None&Common_EarlyChildhoodReportCategory=AllStudents"
                )
                text = fetch(page, url)
                tables = extract_tables(text)
                rows = []
                for header, data in tables:
                    if header[:1] == ["Assessment Name"] and "Number Assessed" in header and "Percent" not in " ".join(header):
                        if header_out is None:
                            header_out = header + ["grade", "subject", "query_school_year"]
                        for d in data:
                            rows.append(d + [grade, subject, label])
                        break
                if rows:
                    if not out.exists():
                        write_rows(out, header_out, rows)
                    else:
                        write_rows(out, None, rows)
                print(f"  {label} {grade} {subject}: {len(rows)} rows")
                time.sleep(0.3)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA)
        scrape_enrollment(page)
        scrape_graddropout(page)
        scrape_assessment(page)
        browser.close()
    print("Done. Output in", OUT_DIR)


if __name__ == "__main__":
    main()
