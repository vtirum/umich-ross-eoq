"""
ma/mcas_subgroups.py — MCAS results by demographic subgroup

profiles.doe.mass.edu/statereport/mcas.aspx exposes a ddSubGroup dropdown
that controls which student subgroup is reported. The base download.py script
collects All Students only. This script re-POSTs the same form for each
subgroup of interest: gender, race/ethnicity, students with disabilities, and
English Learners — at district and school level, for all available years.

Output: data/raw/ma/assessment/mcas/<year>_<level>_<subgroup>.csv
Manifest: data/raw/ma/mcas_subgroups_manifest.csv

Run:
    python scripts/ma/mcas_subgroups.py
Environment:
    MA_MIN_YEAR=2019   earliest year to pull (default; 0 = all years)
"""

import sys
import os
import csv
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
from bs4 import BeautifulSoup

from common.http_client import make_session
from common.manifest import write_csv

BASE = "https://profiles.doe.mass.edu/statereport/"
SLUG = "mcas"
OUT_DIR = Path("data/raw/ma/assessment/mcas_subgroups")
MANIFEST_PATH = Path("data/raw/ma/mcas_subgroups_manifest.csv")
MIN_YEAR = int(os.environ.get("MA_MIN_YEAR", "2019"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

# Subgroup values from ddSubGroup — skip '100' (All Students), collected by download.py
TARGET_SUBGROUPS = {
    "601": "Male",
    "602": "Female",
    "501": "Black_AfricanAmerican",
    "503": "Asian",
    "504": "Hispanic_Latino",
    "502": "AmericanIndian_AlaskaNative",
    "506": "NativeHawaiian_PacificIslander",
    "505": "MultiRace_NonHispanic",
    "507": "White",
    "301": "Students_with_Disabilities",
    "401": "English_Learners",
    "801": "High_Needs",
}

MANIFEST_FIELDS = [
    "state", "category", "report", "year", "level", "subgroup_code",
    "subgroup_label", "local_path", "status", "rows", "cols",
]


def _form_state(soup):
    out = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        el = soup.find("input", {"name": name})
        out[name] = el["value"] if el and el.has_attr("value") else ""
    return out


def _selects(soup):
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


def _save_table(year, level, subgroup_label, rows):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / f"mcas_{year}_{level}_{subgroup_label}.csv"
    with open(dest, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return dest


def _post(session, base_state, selects, year_field, year, rt_field, level_value,
          sg_field, sg_value):
    data = dict(base_state)
    data["__EVENTTARGET"] = year_field
    data["__EVENTARGUMENT"] = ""
    for name, opts in selects.items():
        data[name] = opts[0][0] if opts else ""
    data[year_field] = year
    if rt_field:
        data[rt_field] = level_value
    if sg_field:
        data[sg_field] = sg_value
    resp = session.post(BASE + f"{SLUG}.aspx", data=data, timeout=60)
    if resp.status_code != 200:
        return None, f"http_{resp.status_code}"
    table = _biggest_table(BeautifulSoup(resp.text, "html.parser"))
    if not table:
        return None, "no_table"
    rows = _table_to_rows(table)
    return rows, "ok"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)

    print(f"Fetching MCAS form at {BASE}{SLUG}.aspx ...")
    r = session.get(BASE + f"{SLUG}.aspx", timeout=45)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    base_state = _form_state(soup)
    selects = _selects(soup)

    year_field = next((n for n in selects if n.endswith("ddYear")), None)
    rt_field = next((n for n in selects if "ReportType" in n), None)
    sg_field = next((n for n in selects if "SubGroup" in n or "subgroup" in n.lower()), None)

    if not year_field:
        print("ERROR: could not find year dropdown")
        return
    if not sg_field:
        print("ERROR: could not find subgroup dropdown")
        return

    print(f"year_field={year_field}, rt_field={rt_field}, sg_field={sg_field}")

    years = [v for v, _ in selects[year_field] if v.isdigit() and int(v) >= MIN_YEAR]
    if rt_field:
        levels = [(v, t.lower()) for v, t in selects[rt_field]
                  if t.strip().lower() in ("district", "school")]
    else:
        levels = [("", "district")]

    print(f"Years: {years}, Levels: {[l for _,l in levels]}, Subgroups: {len(TARGET_SUBGROUPS)}")
    total = len(years) * len(levels) * len(TARGET_SUBGROUPS)
    print(f"Total requests: {total}")

    manifest = []
    combos = [
        (year, level_value, level_name, sg_code, sg_label)
        for year in years
        for level_value, level_name in levels
        for sg_code, sg_label in TARGET_SUBGROUPS.items()
    ]

    for year, level_value, level_name, sg_code, sg_label in tqdm.tqdm(combos, desc="MCAS subgroups"):
        dest = OUT_DIR / f"mcas_{year}_{level_name}_{sg_label}.csv"
        row = {
            "state": "MA", "category": "assessment", "report": "mcas",
            "year": year, "level": level_name,
            "subgroup_code": sg_code, "subgroup_label": sg_label,
            "local_path": str(dest), "status": "", "rows": "", "cols": "",
        }
        if dest.exists() and dest.stat().st_size > 0:
            nrows = sum(1 for _ in open(dest)) - 1
            row.update(status="skipped_existing", rows=nrows)
            manifest.append(row)
            continue
        try:
            rows, status = _post(session, base_state, selects, year_field, year,
                                 rt_field, level_value, sg_field, sg_code)
            if rows and len(rows) > 1:
                dest = _save_table(year, level_name, sg_label, rows)
                row.update(status="saved", rows=len(rows) - 1,
                           cols=len(rows[0]), local_path=str(dest))
            else:
                row.update(status=f"empty:{status}")
        except Exception as e:
            row.update(status=f"error:{str(e)[:50]}")
        manifest.append(row)
        time.sleep(0.5)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    saved = sum(1 for r in manifest if r["status"] in ("saved", "skipped_existing"))
    print(f"\nDone. {saved}/{len(manifest)} tables. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
