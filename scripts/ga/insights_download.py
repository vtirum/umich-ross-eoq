"""
ga/insights_download.py — Georgia DOE Insights data downloads (complements GOSA)

georgiainsights.gadoe.org/data-downloads/ is a Power BI report that catalogs
~485 data files hosted on an Azure blob container
(stgadoegidatadownloads.blob.core.windows.net/datadownloads/). The container is
not publicly listable, so the file URLs are discovered by capturing the Power BI
report's query responses (analysis.windows.net), which embed the full blob URLs.

This data is COMPLEMENTARY to the GOSA repository (scripts/ga/download.py):
  - CCRPI accountability components (achievement, progress, climate, readiness, ...)
  - WIDA ACCESS English-learner assessment state results
  - EOC course-level results
  - CTAE pathways, Whole Child, Student data

Two phases:
  1. Playwright: load the page, capture PBI query JSON, extract blob URLs.
  2. requests: download each (URL-encoded), skip-existing + sha256 + manifest.

Run:
    python scripts/ga/insights_download.py
Environment:
    GA_INSIGHTS_MIN_YEAR=0   only download files whose parsed year >= this (default 0 = all)
"""

import sys
import os
import re
import time
from pathlib import Path
from urllib.parse import quote, urlparse, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
from playwright.sync_api import sync_playwright

from common.file_utils import safe_filename, sha256_file
from common.http_client import make_session
from common.manifest import write_csv
from common.playwright_capture import new_browser_context

PAGE = "https://georgiainsights.gadoe.org/data-downloads/"
BLOB_RE = re.compile(r"https://stgadoegidatadownloads\.blob\.core\.windows\.net/datadownloads/[^\"\\,\]]+")
OUT_DIR = Path("data/raw/ga/insights")
MANIFEST_PATH = OUT_DIR / "insights_manifest.csv"
MIN_YEAR = int(os.environ.get("GA_INSIGHTS_MIN_YEAR", "0"))

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

MANIFEST_FIELDS = [
    "state", "category", "year", "blob_path", "file_url",
    "local_path", "status", "size_bytes", "sha256",
]


def discover_urls():
    """Load the Power BI page and extract all Azure blob file URLs from query responses."""
    captured = []

    def on_resp(r):
        if "analysis.windows.net" in r.url and r.request.method == "POST":
            try:
                captured.append(r.text())
            except Exception:
                pass

    with sync_playwright() as p:
        browser, context = new_browser_context(p, headless=True)
        page = context.new_page()
        page.on("response", on_resp)
        page.goto(PAGE, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(15000)
        browser.close()

    urls = set()
    for blob in captured:
        for m in BLOB_RE.findall(blob):
            # Trim trailing escape/quote artifacts; keep only real file URLs
            u = m.rstrip("\\").strip()
            if re.search(r"\.(xlsx?|csv|zip)$", u, re.I):
                urls.add(u)
    return sorted(urls)


def _category(url):
    seg = url.split("/datadownloads/", 1)[1].split("/")
    return seg[0] if seg else "other"


def _year(url):
    name = unquote(url.split("/")[-1])
    m = re.search(r"(20\d{2})", name)
    return int(m.group(1)) if m else 0


def _download(session, url):
    category = _category(url)
    year = _year(url)
    blob_path = url.split("/datadownloads/", 1)[1]
    out_dir = OUT_DIR / category
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / safe_filename(unquote(Path(urlparse(url).path).name))

    row = {
        "state": "GA", "category": category, "year": year, "blob_path": blob_path,
        "file_url": url, "local_path": str(dest), "status": "", "size_bytes": "", "sha256": "",
    }
    if dest.exists() and dest.stat().st_size > 0:
        row.update(status="skipped_existing", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
        return row
    enc = quote(url, safe=":/")
    with session.get(enc, stream=True, timeout=180) as resp:
        if resp.status_code >= 400:
            row["status"] = f"http_{resp.status_code}"
            return row
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=2 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    row.update(status="downloaded", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
    return row


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Phase 1: discovering blob URLs from the Power BI report...")
    urls = discover_urls()
    print(f"Discovered {len(urls)} files")
    if MIN_YEAR > 0:
        urls = [u for u in urls if _year(u) == 0 or _year(u) >= MIN_YEAR]
        print(f"Year filter >= {MIN_YEAR}: {len(urls)} files")

    if not urls:
        print("No URLs discovered — the Power BI report may not have rendered. Rerun.")
        return

    from collections import Counter
    print("By category:", dict(Counter(_category(u) for u in urls)))

    print("\nPhase 2: downloading...")
    session = make_session(headers=HEADERS)
    manifest = []
    for url in tqdm.tqdm(urls, desc="GA Insights"):
        try:
            manifest.append(_download(session, url))
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {url[:70]}: {e}")
            manifest.append({
                "state": "GA", "category": _category(url), "year": _year(url),
                "blob_path": url.split("/datadownloads/", 1)[-1], "file_url": url,
                "local_path": "", "status": f"error:{str(e)[:50]}", "size_bytes": "", "sha256": "",
            })
        time.sleep(0.3)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    total = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit())
    print(f"\nDone. {ok}/{len(manifest)} files ({total/1e9:.2f} GB). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
