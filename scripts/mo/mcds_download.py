"""
mo/mcds_download.py — Missouri MCDS bulk data files (apps.dese.mo.gov/MCDS)

Missouri's public education data lives in the Missouri Comprehensive Data System
(MCDS) portal. Each dataset is a direct statewide bulk file served by a download
handler:

    https://apps.dese.mo.gov/MCDS/FileDownloadWebHandler.ashx?filename=<hash><name>.xlsx

The category pages (home.aspx?categoryid=N&view=2) render their file lists in
JavaScript, so we harvest the links with a browser, then download each file with
plain requests (the handler itself is not bot-gated and sets a Content-Disposition
filename). Covers all five categories: assessment (MAP results by content area/
grade, disaggregated by subgroup; statewide score distributions), enrollment
(district/building enrollment + demographics back to 1991, attendance), finance
(per-pupil expenditures, ASBR summaries), staff (faculty, certification, student-
staff ratios), graduation (adjusted cohort rate, dropout, follow-up), and
discipline (building/district incidents, Part B).

Not included: the MCDS "SSRS" report-viewer reports (SSRS_Print.aspx?Reportid=...)
and the interactive Visualizations dashboards — those are per-district parameterized
report tools, not bulk files (tracked as a follow-up).

Output:  data/raw/mo/mcds/<category>/<filename>
Manifest: data/raw/mo/mcds/manifest.csv

Run:
    python scripts/mo/mcds_download.py
Environment:
    HEADLESS=1        run the link-harvest browser without a window (recommended)
    MO_CATEGORIES=0,1,2,3,4,5,6,7   category ids to crawl (default 0-7, deduped)
"""

import sys
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
from playwright.sync_api import sync_playwright

from common.playwright_capture import is_headless
from common.file_utils import safe_filename, sha256_file
from common.http_client import make_session
from common.manifest import write_csv

OUT_DIR = Path("data/raw/mo/mcds")
MANIFEST_PATH = OUT_DIR / "manifest.csv"
CAT_URL = "https://apps.dese.mo.gov/MCDS/home.aspx?categoryid={cat}&view=2"
CATEGORIES = [int(x) for x in os.environ.get("MO_CATEGORIES", "0,1,2,3,4,5,6,7").split(",")]

STEALTH_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": STEALTH_UA, "Referer": "https://apps.dese.mo.gov/MCDS/",
           "Accept-Language": "en-US,en;q=0.9"}

MANIFEST_FIELDS = ["state", "category", "label", "file_url", "local_path",
                   "status", "size_bytes", "sha256"]

CATEGORY_KEYWORDS = {
    "assessment": ["map ", "assess", "eoc", "proficien", "content area", "score", "act ", "sat "],
    "enrollment": ["enroll", "member", "attendance", "demograph", "mobility", "student characteristic"],
    "graduation": ["grad", "dropout", "cohort", "follow-up", "completion"],
    "discipline": ["discipl", "suspen", "expul", "safety", "incident"],
    "staff":      ["staff", "teacher", "faculty", "certif", "salary", "educator", "ratio"],
    "finance":    ["financ", "expenditure", "revenue", "asbr", "valuation", "tax", "per pupil", "per ada", "levy"],
}


def _category(label):
    low = label.lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(k in low for k in kws):
            return cat
    return "other"


def _harvest_links():
    """Browse each MCDS category page and collect (label, url) for every bulk file."""
    files = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=is_headless(),
                                     args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=STEALTH_UA, viewport={"width": 1440, "height": 900},
                                  locale="en-US", timezone_id="America/Chicago")
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()
        for cat in CATEGORIES:
            try:
                page.goto(CAT_URL.format(cat=cat), wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"  category {cat}: nav error {str(e)[:60]}")
                continue
            time.sleep(3)
            # expand any collapsed accordion sections to reveal all file links
            try:
                page.evaluate(
                    "() => document.querySelectorAll("
                    "'[aria-expanded=false],.collapsed,.accordion-toggle,a[data-toggle]')"
                    ".forEach(e => { try { e.click(); } catch (_) {} })")
                time.sleep(1)
            except Exception:
                pass
            found = page.evaluate(
                "() => [...document.querySelectorAll('a[href]')]"
                ".filter(a => a.href.includes('FileDownloadWebHandler.ashx'))"
                ".map(a => ({t: (a.textContent||'').trim().slice(0,120), h: a.href}))")
            new = 0
            for it in found:
                if it["h"] not in files:
                    files[it["h"]] = it["t"]
                    new += 1
            print(f"  category {cat}: {len(found)} links ({new} new)")
        browser.close()
    return files


def _filename(resp, url, label):
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
    name = unquote(m.group(1)).strip() if m else ""
    if not name:
        # fall back to the filename= query param, stripping the leading hash
        m2 = re.search(r"filename=([^&]+)", url)
        name = unquote(m2.group(1)) if m2 else (safe_filename(label) + ".xlsx")
        name = re.sub(r"^[0-9a-f]{8}", "", name)  # strip the GUID prefix
    return safe_filename(name)


def _download(session, url, label):
    category = _category(label)
    row = {"state": "MO", "category": category, "label": label, "file_url": url,
           "local_path": "", "status": "", "size_bytes": "", "sha256": ""}
    try:
        resp = session.get(url, timeout=180, stream=True)
    except Exception as e:
        row["status"] = f"error:{str(e)[:50]}"
        return row
    if resp.status_code >= 400:
        row["status"] = f"http_{resp.status_code}"
        return row
    fname = _filename(resp, url, label)
    dest = OUT_DIR / category / fname
    dest.parent.mkdir(parents=True, exist_ok=True)
    row["local_path"] = str(dest)
    if dest.exists() and dest.stat().st_size > 0:
        row.update(status="skipped_existing", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
        return row
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    if dest.stat().st_size < 50:
        dest.unlink()
        row["status"] = "too_small"
        return row
    row.update(status="downloaded", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
    return row


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Harvesting MCDS category pages...")
    files = _harvest_links()
    print(f"Total unique bulk files: {len(files)}")

    from collections import Counter
    print("By category:", dict(Counter(_category(t) for t in files.values()).most_common()))

    session = make_session(headers=HEADERS)
    manifest = []
    for url, label in tqdm.tqdm(files.items(), desc="MO MCDS downloads"):
        manifest.append(_download(session, url, label))
        time.sleep(0.1)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    mb = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit()) / 1e6
    print(f"\nDone. {ok}/{len(manifest)} files ({mb:.1f} MB). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
