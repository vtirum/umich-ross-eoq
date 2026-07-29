"""
ut/datagateway_proficiency.py — Utah RISE/UA Plus/DLM proficiency BY DEMOGRAPHIC GROUP

Closes the Utah "assessments by gender" gap. Utah's static reports
(schools.utah.gov/datastatistics/reports) publish proficiency broken out by
race, disability, and ELL — but NOT by gender. The public USBE Data Gateway
"Student Proficiency Results" dashboard does: its demographic table includes
Female / Male alongside race, Economically Disadvantaged, LEP, Students with
Disabilities, and Mobile.

That dashboard is a Tableau Cloud view embedded via the Tableau Embedding API v3
with a Connected-App JWT the datagateway page mints. We can't hit the Tableau
server directly (no JWT), but we CAN load the public page in a browser — which
authenticates the embed automatically — and then read the underlying worksheet
data through the in-page Embedding API (`getSummaryDataAsync`). That is the
official, supported extraction path.

Granularity: the demographic breakdown is STATE-level only (toggling "Show LEA"
does not add LEA rows to the categories worksheet). So this delivers, per school
year and per subject (Language Arts / Mathematics / Science):
  - % proficient for each demographic Category (incl. Male / Female)
  - the All-Students baseline + masked student counts

Years: the URL year segment is ignored (every route defaults to the latest year).
The year is a categorical filter on the worksheet, so we load the page once and
iterate school years via applyFilterAsync("School Year", ["2021-2022"], replace).

Output: data/raw/ut/assessment_gender_datagateway/
  proficiency_by_category_<schoolyear>.csv   (one per year)
  proficiency_by_category_all_years.csv      (combined)
Manifest: data/raw/ut/assessment_gender_datagateway/manifest.csv

Run:
    python scripts/ut/datagateway_proficiency.py
Environment:
    HEADLESS=1            run without a visible browser (recommended)
    UT_DG_YEARS=2016-2025 inclusive spring-year range to attempt (default 2016-2025);
                          years with no data on the dashboard are skipped automatically
"""

import sys
import os
import csv
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from common.playwright_capture import new_browser_context, is_headless
from common.file_utils import sha256_file
from common.manifest import write_csv

OUT_DIR = Path("data/raw/ut/assessment_gender_datagateway")
MANIFEST_PATH = OUT_DIR / "manifest.csv"
PAGE = "https://datagateway.schools.utah.gov/Assessment/StudentProficiency/2024/StudentProficiencyPublic"

DEFAULT_YEARS = os.environ.get("UT_DG_YEARS", "2016-2025")

MANIFEST_FIELDS = [
    "state", "source", "school_year", "level", "n_rows",
    "local_path", "status", "size_bytes", "sha256",
]

# In-page JS: wait for the Tableau embed to become interactive.
JS_READY = r"""
async () => {
  const viz = document.querySelector('tableau-viz');
  if (!viz) return {err: 'no tableau-viz element'};
  let t = 0;
  while (!viz.workbook && t < 60) { await new Promise(r => setTimeout(r, 500)); t++; }
  return viz.workbook ? {ok: true} : {err: 'workbook never became interactive'};
}
"""

# In-page JS: apply a School Year filter and read the demographic worksheet
# (Category x Subject x % proficient) plus the all-students baseline. Returns the
# actually-applied School Year so mismatches (invalid year) can be detected.
JS_EXTRACT = r"""
async (schoolYear) => {
  const viz = document.querySelector('tableau-viz');
  const wb = viz.workbook;
  const sheet = wb.activeSheet;
  const wss = sheet.worksheets || [sheet];
  const findWs = (re) => wss.find(w => re.test(w.name));
  const cat = findWs(/All Categories/i);
  const all = findWs(/All Students/i);

  if (schoolYear) {
    try { await cat.applyFilterAsync('School Year', [schoolYear], 'replace'); }
    catch (e) { return { err: 'applyFilter:' + String(e).slice(0, 100) }; }
    await new Promise(r => setTimeout(r, 3500));
  }

  const dump = async (ws) => {
    const d = await ws.getSummaryDataAsync({ maxRows: 100000, ignoreSelection: true });
    return { cols: d.columns.map(c => c.fieldName),
             rows: d.data.map(r => r.map(c => c.formattedValue)) };
  };

  const out = { schoolYear: null, categories: null, allStudents: null };
  try {
    const fs = await cat.getFiltersAsync();
    const fy = fs.find(f => /School Year/i.test(f.fieldName));
    if (fy && fy.appliedValues && fy.appliedValues.length)
      out.schoolYear = fy.appliedValues.map(v => v.formattedValue).join(',');
  } catch (e) {}
  if (cat) out.categories = await dump(cat);
  if (all) out.allStudents = await dump(all);
  return out;
}
"""


def _parse_years(spec):
    a, b = spec.split("-")
    # spring year N -> school year "N-1 - N"
    return [f"{n-1}-{n}" for n in range(int(a), int(b) + 1)]


def _write_csv(path, cols, rows, extra_cols):
    """extra_cols: list of (name, value) prepended to every row."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [c for c, _ in extra_cols] + cols
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        prefix = [v for _, v in extra_cols]
        for r in rows:
            w.writerow(prefix + r)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    school_years = _parse_years(DEFAULT_YEARS)
    headless = is_headless()

    manifest = []
    combined_rows = []          # rows for the all-years file
    combined_cols = None
    seen_years = set()

    with sync_playwright() as pw:
        browser, ctx = new_browser_context(pw, headless=headless)
        page = ctx.new_page()

        print(f"Loading {PAGE}")
        page.goto(PAGE, wait_until="domcontentloaded", timeout=60000)
        # Tableau keeps a live connection, so networkidle never fires; poll the API.
        ready = None
        for _ in range(8):
            time.sleep(3)
            ready = page.evaluate(JS_READY)
            if ready and ready.get("ok"):
                break
        if not ready or not ready.get("ok"):
            print(f"  viz never became interactive: {(ready or {}).get('err')}")
            browser.close()
            return

        for sy in school_years:
            res = page.evaluate(JS_EXTRACT, sy)
            if res.get("err"):
                print(f"  {sy}: {res['err']}")
                continue
            applied = res.get("schoolYear")
            cats = res.get("categories")
            # Skip years the dashboard rejected or has no data for
            if applied != sy or not cats or not cats["rows"]:
                print(f"  {sy}: no data (applied={applied})")
                continue
            if sy in seen_years:
                continue
            seen_years.add(sy)

            sy_safe = sy.replace("/", "-").replace(",", "_")
            dest = OUT_DIR / f"proficiency_by_category_{sy_safe}.csv"
            _write_csv(dest, cats["cols"], cats["rows"],
                       [("state", "UT"), ("school_year", sy), ("level", "State")])
            print(f"  {sy}: {len(cats['rows'])} category rows -> {dest.name}")
            manifest.append(_row(sy, "State", len(cats["rows"]), dest, "downloaded"))

            if combined_cols is None:
                combined_cols = cats["cols"]
            for r in cats["rows"]:
                combined_rows.append(["UT", sy, "State"] + r)

        browser.close()

    if combined_rows:
        allp = OUT_DIR / "proficiency_by_category_all_years.csv"
        with open(allp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["state", "school_year", "level"] + combined_cols)
            w.writerows(combined_rows)
        print(f"\nCombined: {len(combined_rows)} rows -> {allp}")

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] == "downloaded")
    print(f"Done. {ok}/{len(manifest)} year-files. Manifest: {MANIFEST_PATH}")


def _row(school_year, level, n_rows, dest, status):
    row = {
        "state": "UT", "source": "usbe_datagateway_tableau", "school_year": school_year,
        "level": level, "n_rows": n_rows, "local_path": str(dest) if dest else "",
        "status": status, "size_bytes": "", "sha256": "",
    }
    if dest and Path(dest).exists():
        row["size_bytes"] = Path(dest).stat().st_size
        row["sha256"] = sha256_file(dest)
    return row


if __name__ == "__main__":
    main()
