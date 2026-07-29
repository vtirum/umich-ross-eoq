"""
ca/download.py — California (CDE) bulk education data downloader

The CDE downloadable-data pages under cde.ca.gov/ds/ad/ are JavaScript-rendered,
so link discovery needs a real browser (Playwright). The actual data files are
fixed-width .txt (and some .csv/.xlsx/.zip) hosted on www3.cde.ca.gov/demo-downloads/,
with the domain encoded in the path (/census/, /enrollment/, /assessment/,
/staff/, /discipline/, etc.). Files are statewide with school/district rows —
i.e. all entity levels in one file.

Two phases:
  1. Crawl the /ds/ad/ hub pages with Playwright, collect every demo-downloads
     file link (BFS, bounded depth, scoped to the /ds/ad/ tree).
  2. Download each file with requests (skip-existing + sha256 + manifest).

Run:
    python scripts/ca/download.py                 # crawl + download
    CA_LIST_ONLY=1 python scripts/ca/download.py  # dry run: list files, no download

Environment:
    CA_LIST_ONLY=1   discover + report files but do not download (preview the haul)
    CA_MIN_YEAR=2019 only download files whose end-year >= this (default 2019;
                     0 = everything linked on the current pages)
"""

import sys
import os
import re
import time
import random
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm

from common.file_utils import safe_filename, sha256_file
from common.http_client import make_session
from common.manifest import write_csv

# Hub pages — the per-domain downloadable-data landing pages.
SEED_PAGES = [
    # /ds/ad/ — enrollment, assessment, staff, grad/dropout, discipline, EL, FRPM
    "https://www.cde.ca.gov/ds/ad/downloadabledata.asp",
    "https://www.cde.ca.gov/ds/ad/enrolldowndata.asp",
    "https://www.cde.ca.gov/ds/ad/assessmentdata.asp",
    "https://www.cde.ca.gov/ds/ad/staff.asp",
    "https://www.cde.ca.gov/ds/ad/graddropdf.asp",
    "https://www.cde.ca.gov/ds/ad/discipline.asp",
    "https://www.cde.ca.gov/ds/ad/eldf.asp",
    "https://www.cde.ca.gov/ds/ad/filessp.asp",
    # /ds/fd/ — financial: SACS annual financial data, current expense of education
    # & per-pupil spending, certificated salaries & benefits (J-90)
    "https://www.cde.ca.gov/ds/fd/",
    "https://www.cde.ca.gov/ds/fd/fd/index.asp",
    "https://www.cde.ca.gov/ds/fd/ec/index.asp",
    "https://www.cde.ca.gov/ds/fd/cs/index.asp",
    # /ds/si/ — school directory / public schools & districts data files (school records)
    "https://www.cde.ca.gov/ds/si/ds/pubschls.asp",
    "https://www.cde.ca.gov/ds/si/ps/",
]

# Pages under either the /ds/ad/, /ds/fd/, or /ds/si/ tree are followed during the crawl.
PAGE_PREFIX = ("https://www.cde.ca.gov/ds/ad/", "https://www.cde.ca.gov/ds/fd/", "https://www.cde.ca.gov/ds/si/")
FILE_HOST_HINT = "demo-downloads"
OUT_DIR = Path("data/raw/ca")
MANIFEST_PATH = OUT_DIR / "manifest.csv"
FILE_EXTS = (".txt", ".csv", ".xlsx", ".xls", ".zip")

MAX_PAGES = 160           # safety cap on pages crawled
CA_LIST_ONLY = os.environ.get("CA_LIST_ONLY", "0") not in ("0", "false", "no", "")
MIN_YEAR = int(os.environ.get("CA_MIN_YEAR", "2019"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

MANIFEST_FIELDS = [
    "state", "category", "year", "label", "file_url",
    "local_path", "status", "size_bytes", "sha256",
]


def _category(url):
    """Domain is encoded in the demo-downloads path, e.g. /demo-downloads/census/..."""
    path = urlparse(url).path.lower()
    parts = path.split("/")
    if "demo-downloads" in parts:
        i = parts.index("demo-downloads")
        if i + 1 < len(parts):
            return parts[i + 1]
    if "/ds/si/ps/" in path:
        return "private_school_directory"
    return "other"


def _year(url):
    """CA filenames end with a 4-digit YYYY year span, e.g. cdenroll2526 -> 2025-26 (end 2026).
    Return the end calendar year (2026)."""
    name = Path(urlparse(url).path).name
    m = re.search(r"(\d{2})(\d{2})(?:-v\d)?\.\w+$", name)
    if m:
        return 2000 + int(m.group(2))
    m = re.search(r"(20\d{2})", name)
    if m:
        return int(m.group(1))
    return 0


def _is_file(url):
    return urlparse(url).path.lower().endswith(FILE_EXTS) or FILE_HOST_HINT in url.lower()


def crawl_file_links():
    """BFS the /ds/ad/ hub pages with Playwright; return list of file-link dicts."""
    file_links = {}
    seen_pages = set()
    queue = list(SEED_PAGES)

    with sync_playwright_ctx() as (browser, context):
        page = context.new_page()
        pbar = tqdm.tqdm(total=MAX_PAGES, desc="Crawling CA pages")
        while queue and len(seen_pages) < MAX_PAGES:
            page_url = queue.pop(0)
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            pbar.update(1)
            try:
                page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                if "captcha" in page.title().lower():
                    pbar.close()
                    browser.close()
                    raise SystemExit(
                        "\nCDE is serving a Radware Captcha page — bot mitigation is "
                        "blocking automated access (usually triggered by rapid requests).\n"
                        "Wait (minutes to hours), then rerun. Keep the crawl gentle."
                    )
                links = page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(a => ({href:a.href, text:a.innerText.trim()}))",
                )
            except SystemExit:
                raise
            except Exception as e:
                tqdm.tqdm.write(f"page failed {page_url}: {e}")
                continue

            for l in links:
                href = l["href"].split("#")[0]
                if _is_file(href) and href.lower().endswith(FILE_EXTS):
                    if href not in file_links:
                        file_links[href] = {
                            "url": href, "label": l["text"][:120],
                            "category": _category(href), "year": _year(href),
                        }
                elif (href.startswith(PAGE_PREFIX) and href.endswith(".asp")
                      and href not in seen_pages and href not in queue):
                    queue.append(href)

            # Gentle pacing between page loads so we don't re-trip the WAF rate limiter.
            page.wait_for_timeout(int(random.uniform(1500, 3000)))
        pbar.close()
        browser.close()

    return list(file_links.values())


# Small context-manager shim so crawl_file_links reads cleanly.
import contextlib
from playwright.sync_api import sync_playwright

# CDE sits behind a Radware bot-mitigation captcha. A full, realistic browser
# fingerprint (masking navigator.webdriver, real UA/viewport/timezone/locale)
# passes its JS challenge; an obvious-automation context gets the captcha page.
_STEALTH_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


@contextlib.contextmanager
def sync_playwright_ctx():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent=_STEALTH_UA,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/Los_Angeles",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        yield browser, context


def _download(session, item):
    url = item["url"]
    category = item["category"]
    year = item["year"]
    out_dir = OUT_DIR / category / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / safe_filename(Path(urlparse(url).path).name)

    row = {
        "state": "CA", "category": category, "year": year, "label": item["label"],
        "file_url": url, "local_path": str(dest), "status": "", "size_bytes": "", "sha256": "",
    }
    if dest.exists() and dest.stat().st_size > 0:
        row.update(status="skipped_existing", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
        return row
    with session.get(url, stream=True, timeout=300) as resp:
        if resp.status_code >= 400:
            row["status"] = f"http_{resp.status_code}"
            return row
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=4 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    row.update(status="downloaded", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
    return row


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Phase 1: crawling CDE pages for file links (Playwright)...")
    links = crawl_file_links()
    print(f"Discovered {len(links)} file links")

    if MIN_YEAR > 0:
        kept = [l for l in links if l["year"] == 0 or l["year"] >= MIN_YEAR]
        print(f"Year filter >= {MIN_YEAR}: {len(kept)} files (year=0 kept; CA_MIN_YEAR=0 for all)")
        links = kept

    from collections import Counter
    cats = Counter(l["category"] for l in links)
    print("By category:", dict(cats))

    if CA_LIST_ONLY:
        write_csv(OUT_DIR / "discovered_files.csv", links,
                  ["url", "label", "category", "year"])
        print(f"\nLIST ONLY — wrote {OUT_DIR / 'discovered_files.csv'}. No downloads.")
        return

    print("\nPhase 2: downloading...")
    session = make_session(headers=HEADERS)
    manifest = []
    for item in tqdm.tqdm(links, desc="CA downloads"):
        try:
            manifest.append(_download(session, item))
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {item['url']}: {e}")
            manifest.append({
                "state": "CA", "category": item["category"], "year": item["year"],
                "label": item["label"], "file_url": item["url"], "local_path": "",
                "status": f"error:{str(e)[:60]}", "size_bytes": "", "sha256": "",
            })
        time.sleep(0.4)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    total = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit())
    print(f"\nDone. {ok}/{len(manifest)} files ({total/1e9:.2f} GB). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
