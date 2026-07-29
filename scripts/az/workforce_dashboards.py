"""
az/workforce_dashboards.py — Arizona educator/teacher workforce data (Power BI)

Closes the Arizona "bulk staff records" gap as far as ADE publishes it. ADE does
NOT release a downloadable teacher/staff file (SDER is PDFs; OACIS is per-educator
lookup only). Its one bulk, demographic teacher-workforce source is the public
Power BI "ADE Workforce Data Dashboards" (self-reported via the Teacher Input
Application, TIA), embedded at azed.gov/teach/ade-workforce-data-dashboards.

Two public reports:
  Educator Dashboard (3 pages)
    - Degree & Years of Experience (education level, experience buckets + trends)
    - Content & Grade Level (subject taught, grade band)
    - Race & Gender (race + gender distributions + trends 2020-2026)
  Comparison of Students vs Teachers - Ethnicity Makeup (student vs teacher race)

How the extraction works: a Power BI "view" embed renders its visuals by POSTing
to <region>.analysis.windows.net/public/reports/querydata and getting back the
compressed "DSR" result. We load the embed in a browser, nudge it so every visual
issues its query, capture each querydata response, and decode the DSR into tidy
rows. Column names come from the response's descriptor.Select. We save one CSV per
visual plus the raw JSON payloads as an audit trail.

Granularity: TIA state-level aggregates. Distribution visuals reflect the report's
default year; the trend visuals carry the full 2020-2026 year dimension. (School-
level teacher counts by race/sex/experience are covered separately by CRDC.)

Output: data/raw/az/workforce/<report>/<visual>.csv
        data/raw/az/workforce/<report>/_raw/<visual>.json
Manifest: data/raw/az/workforce/manifest.csv

Run:
    python scripts/az/workforce_dashboards.py
Environment:
    HEADLESS=1   run without a visible browser (recommended)
"""

import sys
import os
import re
import csv
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from common.playwright_capture import new_browser_context, is_headless
from common.file_utils import safe_filename, sha256_file
from common.manifest import write_csv

OUT_DIR = Path("data/raw/az/workforce")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

REPORTS = [
    {
        "name": "educator_dashboard",
        "embed": "https://app.powerbi.com/view?r=eyJrIjoiMjRjODcxZTktOGY3MC00Nzc3LWIyZGQtMTk4NjMzZjdmOTIxIiwidCI6IjU4YTViMGNiLTQ0MWYtNDJiYS1hNWExLThmZGZkMDVhM2ZmYyIsImMiOjZ9",
        "pages": 3,
    },
    {
        "name": "students_vs_teachers_ethnicity",
        "embed": "https://app.powerbi.com/view?r=eyJrIjoiNzU5OWI3OTgtYWIyYy00NDZhLWIxMmEtNWNmZDgxZmI3MTM0IiwidCI6IjU4YTViMGNiLTQ0MWYtNDJiYS1hNWExLThmZGZkMDVhM2ZmYyIsImMiOjZ9",
        "pages": 1,
    },
]

MANIFEST_FIELDS = [
    "state", "source", "report", "page", "visual", "columns", "n_rows",
    "local_path", "status", "size_bytes", "sha256",
]


# DSR decoding + capture helpers are shared with Indiana's EdData dashboards.
from common.powerbi import (  # noqa: E402
    decode_querydata, _nudge, _next_page, _slug, _capture_report,
)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    headless = is_headless()
    manifest = []

    with sync_playwright() as pw:
        browser, ctx = new_browser_context(pw, headless=headless)

        for report in REPORTS:
            print(f"\n=== {report['name']} ===")
            page = ctx.new_page()
            try:
                by_page = _capture_report(page, report)
            except Exception as e:
                print(f"  capture error: {str(e)[:120]}")
                page.close()
                continue
            page.close()

            rep_dir = OUT_DIR / report["name"]
            raw_dir = rep_dir / "_raw"
            rep_dir.mkdir(parents=True, exist_ok=True)
            raw_dir.mkdir(parents=True, exist_ok=True)

            taken = set()
            # dedupe: keep the decoded table with the most rows per (page, column-signature)
            best = {}
            for pidx, bodies in by_page.items():
                for payload in bodies:
                    for columns, rows in decode_querydata(payload):
                        sig = (pidx, tuple(columns))
                        if sig not in best or len(rows) > len(best[sig][1]):
                            best[sig] = (columns, rows, payload)

            n_visuals = 0
            for (pidx, _sig), (columns, rows, payload) in sorted(best.items()):
                slug = _slug(columns, taken)
                dest = rep_dir / f"p{pidx}_{slug}.csv"
                with open(dest, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(columns)
                    w.writerows(rows)
                (raw_dir / f"p{pidx}_{slug}.json").write_text(json.dumps(payload)[:500000])
                n_visuals += 1
                manifest.append({
                    "state": "AZ", "source": "ade_workforce_powerbi", "report": report["name"],
                    "page": pidx, "visual": slug, "columns": "|".join(columns), "n_rows": len(rows),
                    "local_path": str(dest), "status": "downloaded",
                    "size_bytes": dest.stat().st_size, "sha256": sha256_file(dest),
                })
                print(f"  p{pidx} {slug}: {len(rows)} rows")
            if n_visuals == 0:
                print("  no visuals decoded (report may not have rendered)")
                manifest.append({
                    "state": "AZ", "source": "ade_workforce_powerbi", "report": report["name"],
                    "page": "", "visual": "", "columns": "", "n_rows": 0,
                    "local_path": "", "status": "no_data", "size_bytes": "", "sha256": "",
                })

        browser.close()

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] == "downloaded")
    print(f"\nDone. {ok} visuals captured. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
