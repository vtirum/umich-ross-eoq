"""
in/eddata_dashboards.py — Indiana EdData dashboards (Power BI)

The IDOE Data Center publishes bulk files for assessment, enrollment, graduation and
staff, but its FINANCE data is not a file: Form 9 (revenue, expenditure and cash
balances for every school corporation and charter) lives only in the EdData portal
as an embedded Power BI report. Attendance/enrollment and 3rd-grade-reading also
have dashboards there with detail beyond the static files.

eddata.doe.in.gov serves these with powerbigov.min.js — the same Power BI embed
technology as Arizona's ADE Workforce dashboards — so we reuse the shared DSR
capture/decoder in scripts/common/powerbi.py.

One wrinkle vs Arizona: EdData does not expose an app.powerbi.com "view" URL. Each
report page wraps a cross-origin <iframe> pointing at **app.powerbigov.us**
(Power BI Government cloud), whose querydata calls go to
*.analysis.usgovcloudapi.net. The iframe src is generated per page load, so we load
the wrapper first, read the iframe's src, then drive that embed directly.

Reports are addressed by UUID:
    https://eddata.doe.in.gov/PublicHome/GetObjectByUuidAndViewType
        ?uuid=<UUID>&viewType=Report&currentPage=1

Output: data/raw/in/eddata/<report>/<visual>.csv  (+ _raw/<visual>.json)
Manifest: data/raw/in/eddata/manifest.csv

Run:
    python scripts/in/eddata_dashboards.py
Environment:
    HEADLESS=1   run without a visible browser (recommended)
"""

import sys
import csv
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from common.playwright_capture import new_browser_context, is_headless
from common.file_utils import sha256_file
from common.manifest import write_csv
from common.powerbi import decode_querydata, _slug, _capture_report

OUT_DIR = Path("data/raw/in/eddata")
MANIFEST_PATH = OUT_DIR / "manifest.csv"
VIEW = ("https://eddata.doe.in.gov/PublicHome/GetObjectByUuidAndViewType"
        "?uuid={uuid}&viewType=Report&currentPage=1")

# UUIDs are stable identifiers from the EdData public report list.
REPORTS = [
    {"name": "form9_finance", "pages": 4,
     "uuid": "0578b160-8927-46cf-8066-b170a3639fbd"},
    {"name": "third_grade_reading", "pages": 2,
     "uuid": "df4a26e1-eedc-4480-812d-da6cad5528ff"},
]

MANIFEST_FIELDS = ["state", "source", "report", "page", "visual", "columns",
                   "n_rows", "local_path", "status", "size_bytes", "sha256"]


def _capture_wrapper(page, report):
    """Load the EdData wrapper page and capture the embedded report's querydata.

    The powerbigov.us embed only renders inside this wrapper (it needs the parent's
    auth handshake) — navigating straight to the iframe src yields a spinner. So we
    stay on the wrapper and let Playwright record the cross-origin iframe's traffic,
    nudging the page so each visual issues its query. Page-to-page navigation uses
    the wrapper's own ?currentPage= parameter.
    """
    by_page = {}
    bodies = []

    def on_resp(resp):
        if "querydata" in resp.url.lower():
            try:
                bodies.append(resp.json())
            except Exception:
                pass

    page.on("response", on_resp)
    for pidx in range(1, report["pages"] + 1):
        bodies.clear()
        url = VIEW.format(uuid=report["uuid"]).replace("currentPage=1", f"currentPage={pidx}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Power BI Gov renders slowly; nudge to force visuals to query.
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                page.mouse.move(600, 420)
                page.mouse.wheel(0, 90)
                page.mouse.wheel(0, -90)
            except Exception:
                pass
            time.sleep(1.5)
            if len(bodies) >= 4 and time.time() > deadline - 25:
                break
        by_page[pidx] = list(bodies)
        print(f"  page {pidx}: {len(bodies)} querydata responses")
    page.remove_listener("response", on_resp)
    return by_page


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []

    with sync_playwright() as pw:
        browser, ctx = new_browser_context(pw, headless=is_headless())
        for report in REPORTS:
            print(f"\n=== {report['name']} ===")
            page = ctx.new_page()
            try:
                by_page = _capture_wrapper(page, report)
            except Exception as e:
                print(f"  capture error: {str(e)[:120]}")
                page.close()
                continue
            page.close()

            rep_dir = OUT_DIR / report["name"]
            raw_dir = rep_dir / "_raw"
            rep_dir.mkdir(parents=True, exist_ok=True)
            raw_dir.mkdir(parents=True, exist_ok=True)

            taken, best = set(), {}
            for pidx, bodies in by_page.items():
                for payload in bodies:
                    for columns, rows in decode_querydata(payload):
                        sig = (pidx, tuple(columns))
                        if sig not in best or len(rows) > len(best[sig][1]):
                            best[sig] = (columns, rows, payload)

            n = 0
            for (pidx, _sig), (columns, rows, payload) in sorted(best.items()):
                slug = _slug(columns, taken)
                dest = rep_dir / f"p{pidx}_{slug}.csv"
                with open(dest, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(columns)
                    w.writerows(rows)
                (raw_dir / f"p{pidx}_{slug}.json").write_text(json.dumps(payload)[:500000])
                manifest.append({
                    "state": "IN", "source": "eddata_powerbi", "report": report["name"],
                    "page": pidx, "visual": slug, "columns": "|".join(columns),
                    "n_rows": len(rows), "local_path": str(dest), "status": "downloaded",
                    "size_bytes": dest.stat().st_size, "sha256": sha256_file(dest),
                })
                n += 1
                print(f"  p{pidx} {slug[:50]}: {len(rows)} rows")
            if n == 0:
                print("  no visuals decoded (report may not have rendered)")
                manifest.append({"state": "IN", "source": "eddata_powerbi",
                                 "report": report["name"], "page": "", "visual": "",
                                 "columns": "", "n_rows": 0, "local_path": "",
                                 "status": "no_data", "size_bytes": "", "sha256": ""})
        browser.close()

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] == "downloaded")
    print(f"\nDone. {ok} visuals captured. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
