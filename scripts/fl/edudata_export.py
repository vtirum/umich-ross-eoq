"""
edudata_export.py — Extract structured data from edudata.fldoe.org "Know Your Data"

The 10 "Advanced Reports" are Tableau Cloud dashboards hosted on
analytics.fldoe.org (site: fladoeexternal), embedded with a JWT trusted-ticket
("Connected App"). They cannot be scraped as HTML, and the direct Tableau
.csv/crosstab endpoints are auth-walled. Clicking the Tableau download toolbar
from automation does not work (cross-origin iframe + shadow DOM).

This script instead uses the **Tableau Embedding API v3 JavaScript methods** to
pull the underlying worksheet data directly, then serializes it to CSV + JSON:

  1. Fetch the JWT token from edudata's /api/Tableau/GetToken/
  2. For each report, load the edudata page (with a patch for a bug in their JS
     — GetURLParameter is undefined) to discover the current viz src, which
     contains a session-specific workbook suffix that changes over time.
  3. Build a minimal embedding harness served from the edudata.fldoe.org origin
     (required — the Connected App restricts which domains may embed the viz),
     with <tableau-viz src=... token=...>.
  4. Wait for the viz 'firstinteractive' event, enumerate every dashboard tab,
     activate each, and call getSummaryDataReaderAsync() on each worksheet.
  5. Save each worksheet's data as CSV + JSON.

This yields data NOT available from report_cards.py — notably assessment
achievement / mean scale scores, FAST progress monitoring, course enrollments,
accelerated credit, and Florida College System (postsecondary) data.

Run:
    python scripts/fl/edudata_export.py

A visible browser is used (headless tends to be blocked by the Connected App).
"""

import sys
import csv
import json
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from common.manifest import write_csv

EDUDATA = "https://edudata.fldoe.org"
TOKEN_URL = f"{EDUDATA}/api/Tableau/GetToken/"
EMBED_API = "https://analytics.fldoe.org/javascripts/api/tableau.embedding.3.latest.min.js"
HARNESS_URL = f"{EDUDATA}/__edudata_harness__"

OUT_DIR = Path("data/raw/fl/edudata")

# The 10 report query parameters the AdvancedReports index page uses.
REPORT_PARAMS = [
    ("Assessments_Statewide",          "Assessments"),
    ("Assessments_PM_Grades3to10",     "AssessmentsProgressMonitoring"),
    ("Assessments_PM_GradesK2",        "ProgressMonitoringK2"),
    ("College_Career_Accelerated",     "CCA"),
    ("Course_Enrollments",             "CourseEnrollments"),
    ("Student_Enrollments",            "StudentEnrollments"),
    ("HS_Graduation_Rates",            "GraduationRates"),
    ("HS_Graduate_Pathways",           "GraduatePathways"),
    ("FCS_Course_Enrollments",         "FCSCourseEnrollments"),
    ("FCS_Graduation_Rates",           "FCSGraduationRates"),
]

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": f"{EDUDATA}/AdvancedReports_Tableau.html",
    "X-Requested-With": "XMLHttpRequest",
}

# Patches a bug on FLDOE's own page (GetURLParameter is referenced but never
# defined), which otherwise aborts the page's viz-construction logic.
GETURLPARAM_SHIM = (
    "window.GetURLParameter = n => new URLSearchParams(location.search).get(n);"
)

MANIFEST_FIELDS = [
    "report", "report_param", "viz_path", "dashboard", "worksheet",
    "columns", "rows", "csv_path", "status",
]

INTERACTIVE_TIMEOUT_MS = 60000


def get_token():
    """Fetch the Tableau Connected App JWT from edudata."""
    r = requests.get(TOKEN_URL, headers=REQUEST_HEADERS, timeout=20)
    r.raise_for_status()
    token = r.json()
    if not token or not isinstance(token, str):
        raise RuntimeError(f"Unexpected token response: {token!r}")
    return token


def discover_viz_path(page, report_param):
    """Load the edudata page for a report and return the viz src path
    (e.g. 'PK12-Assessments_1716.../ACKNOWLEDGEMENT'), with session suffix."""
    url = f"{EDUDATA}/AdvancedReports_Tableau.html?{report_param}=true"
    page.goto(url, wait_until="domcontentloaded", timeout=25000)
    page.wait_for_selector("tableau-viz", timeout=10000)
    src = page.evaluate("() => document.querySelector('tableau-viz').getAttribute('src')")
    if "/views/" not in src:
        raise RuntimeError(f"Unexpected viz src: {src}")
    return "t/fladoeexternal/views/" + src.split("/views/")[-1]


def _build_harness(viz_src, token):
    return (
        "<!DOCTYPE html><html><head>"
        f'<script type="module" src="{EMBED_API}"></script>'
        "</head><body>"
        f'<tableau-viz id="tv" src="{viz_src}" token="{token}" toolbar="hidden"></tableau-viz>'
        "</body></html>"
    )


# JS run inside the harness page: wait for interactive, then walk every
# dashboard tab and pull each worksheet's summary data.
_EXTRACT_JS = """
async () => {
    const viz = document.querySelector('tableau-viz');
    const interactive = await Promise.race([
        new Promise(r => viz.addEventListener('firstinteractive', () => r('ok'))),
        new Promise(r => setTimeout(() => r('timeout'), %d)),
    ]);
    if (interactive !== 'ok') return { ok: false, stage: 'not_interactive' };

    const wb = viz.workbook;
    const sheets = wb.publishedSheetsInfo.map(s => s.name);
    const out = [];

    for (const sheetName of sheets) {
        try {
            await wb.activateSheetAsync(sheetName);
        } catch (e) { /* some sheets can't be activated; skip */ continue; }

        const active = wb.activeSheet;
        const worksheets = active.sheetType === 'dashboard'
            ? active.worksheets : [active];

        for (const ws of worksheets) {
            try {
                const reader = await ws.getSummaryDataReaderAsync(undefined,
                    { ignoreSelection: true, includeAllColumns: true });
                const table = await reader.getAllPagesAsync();
                await reader.releaseAsync();
                if (!table.totalRowCount) continue;
                out.push({
                    dashboard: sheetName,
                    worksheet: ws.name,
                    columns: table.columns.map(c => c.fieldName),
                    rows: table.data.map(row => row.map(cell => cell.formattedValue)),
                });
            } catch (e) {
                out.push({ dashboard: sheetName, worksheet: ws.name,
                           error: String(e).slice(0, 150) });
            }
        }
    }
    return { ok: true, sheetCount: sheets.length, data: out };
}
""" % INTERACTIVE_TIMEOUT_MS


def _safe(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text)).strip("_")[:80]


def _save_table(report_name, dashboard, worksheet, columns, rows):
    out_dir = OUT_DIR / _safe(report_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{_safe(dashboard)}__{_safe(worksheet)}"
    csv_path = out_dir / f"{stem}.csv"
    json_path = out_dir / f"{stem}.json"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(rows)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"columns": columns, "rows": rows}, f, indent=2)

    return csv_path


def process_report(page, report_name, report_param, token, manifest):
    print(f"\n=== {report_name} ({report_param}) ===")
    try:
        viz_path = discover_viz_path(page, report_param)
    except Exception as e:
        print(f"  viz discovery failed: {e}")
        manifest.append({
            "report": report_name, "report_param": report_param, "viz_path": "",
            "dashboard": "", "worksheet": "", "columns": "", "rows": "",
            "csv_path": "", "status": f"discovery_failed:{str(e)[:60]}",
        })
        return

    viz_src = f"https://analytics.fldoe.org/{viz_path}"
    print(f"  viz: {viz_path}")

    harness = _build_harness(viz_src, token)
    harness_page = page.context.new_page()
    harness_page.route(HARNESS_URL,
        lambda route, request: route.fulfill(status=200, content_type="text/html", body=harness))

    try:
        harness_page.goto(HARNESS_URL, wait_until="domcontentloaded", timeout=25000)
        result = harness_page.evaluate(_EXTRACT_JS)
    except PlaywrightTimeoutError as e:
        print(f"  harness load timeout: {e}")
        result = {"ok": False, "stage": "harness_timeout"}
    finally:
        harness_page.close()

    if not result.get("ok"):
        print(f"  extraction failed: {result.get('stage')}")
        manifest.append({
            "report": report_name, "report_param": report_param, "viz_path": viz_path,
            "dashboard": "", "worksheet": "", "columns": "", "rows": "",
            "csv_path": "", "status": f"failed:{result.get('stage')}",
        })
        return

    tables = result.get("data", [])
    saved = 0
    for t in tables:
        if "error" in t:
            manifest.append({
                "report": report_name, "report_param": report_param, "viz_path": viz_path,
                "dashboard": t["dashboard"], "worksheet": t["worksheet"],
                "columns": "", "rows": "", "csv_path": "", "status": f"ws_error:{t['error'][:50]}",
            })
            continue
        csv_path = _save_table(report_name, t["dashboard"], t["worksheet"], t["columns"], t["rows"])
        saved += 1
        manifest.append({
            "report": report_name, "report_param": report_param, "viz_path": viz_path,
            "dashboard": t["dashboard"], "worksheet": t["worksheet"],
            "columns": len(t["columns"]), "rows": len(t["rows"]),
            "csv_path": str(csv_path), "status": "saved",
        })
        print(f"  saved {t['dashboard']} / {t['worksheet']}: {len(t['rows'])} rows x {len(t['columns'])} cols")

    print(f"  {result.get('sheetCount')} dashboard tabs, {saved} data tables saved")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching Tableau token...")
    token = get_token()
    print(f"  token acquired ({len(token)} chars)")

    manifest = []

    with sync_playwright() as p:
        # Headed: the Connected App tends to reject headless automation.
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=REQUEST_HEADERS["User-Agent"],
            accept_downloads=False,
        )
        # Discovery page reuses one tab; patch the FLDOE page bug up front.
        discovery_page = context.new_page()
        discovery_page.add_init_script(GETURLPARAM_SHIM)

        for report_name, report_param in REPORT_PARAMS:
            try:
                process_report(discovery_page, report_name, report_param, token, manifest)
            except Exception as e:
                print(f"  unexpected error: {e}")
                manifest.append({
                    "report": report_name, "report_param": report_param, "viz_path": "",
                    "dashboard": "", "worksheet": "", "columns": "", "rows": "",
                    "csv_path": "", "status": f"error:{str(e)[:60]}",
                })

        browser.close()

    manifest_path = OUT_DIR / "edudata_manifest.csv"
    write_csv(manifest_path, manifest, MANIFEST_FIELDS)
    saved = sum(1 for r in manifest if r["status"] == "saved")
    total_rows = sum(int(r["rows"]) for r in manifest if r["status"] == "saved")
    print(f"\nDone. {saved} data tables saved ({total_rows} total rows). Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
