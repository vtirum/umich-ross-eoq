"""
nv/doe_download.py — Nevada DOE (doe.nv.gov) data files — non-assessment fill

The Nevada Report Card API (scripts/nv/download.py) yields assessment (SBAC/ACT)
but its non-assessment report builder resists automation. The Nevada DOE website
(doe.nv.gov) — a headless CMS — publishes the rest as direct Excel/CSV downloads
on topic pages under the Office of Assessment, Data & Accountability (ADAM):
  - Enrollment for Nevada Public Schools (per-year student counts, 2016- )
  - Student Investment Division — statewide financial reports (NRS 387-388A)
  - Graduate college-enrollment rates, special education, CTE, state-board reports

This crawler renders the data hub + topic pages with Playwright (JS-rendered),
collects every xlsx/csv/zip link, categorizes by page/filename, and downloads
with skip-existing + sha256 + manifest.

Run:
    python scripts/nv/doe_download.py
"""

import sys
import re
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm

from common.file_utils import safe_filename, sha256_file
from common.http_client import make_session
from common.manifest import write_csv
from common.playwright_capture import new_browser_context

ADAM = ("https://doe.nv.gov/offices/"
        "office-of-assessment-data-and-accountability-management-adam")

SEED_PAGES = [
    f"{ADAM}/office-of-information-technology/data-and-reports",
    f"{ADAM}/office-of-information-technology/enrollment-for-nevada-public-schools",
    "https://doe.nv.gov/offices/student-investment-division",
    "https://doe.nv.gov/datacenter/nevadahighschoolgraduatecollegeenrollmentrates/",
    f"{ADAM}/accountability",
    "https://doe.nv.gov/offices/office-of-comprehensive-student-services",
]

PAGE_HOST = "doe.nv.gov"
OUT_DIR = Path("data/raw/nv/doe")
MANIFEST_PATH = OUT_DIR / "doe_manifest.csv"
FILE_EXTS = (".xlsx", ".xls", ".csv", ".zip", ".pdf")
MAX_PAGES = 40

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}

MANIFEST_FIELDS = [
    "state", "category", "year", "label", "file_url",
    "local_path", "status", "size_bytes", "sha256",
]


def _category(label, url):
    s = f"{label} {url}".lower()
    if "enroll" in s or "student count" in s or "number of student" in s:
        return "enrollment"
    if "nrs 387" in s or "nrs_387" in s or "financ" in s or "chart of account" in s or "investment" in s:
        return "financial"
    if "licens" in s or "staff" in s or "educator" in s or "teacher" in s:
        return "staff"
    if "disciplin" in s or "suspension" in s or "restorative" in s:
        return "discipline"
    if "grad" in s or "cohort" in s or "college enroll" in s:
        return "graduation"
    if "special education" in s or "idea" in s or "sped" in s:
        return "special_education"
    if "cte" in s:
        return "cte"
    if "assess" in s:
        return "assessment_report"
    return "other"


def _year(label, url):
    m = re.search(r"(20\d{2})\s*[-–]?\s*(20\d{2})?", f"{label} {unquote(url)}")
    if m:
        return int(m.group(2) or m.group(1))
    return 0


def crawl_links():
    """Render seed pages + one level of doe.nv.gov sub-pages, collect file links."""
    files = {}
    seen = set()
    queue = list(SEED_PAGES)

    with sync_playwright_ctx() as (browser, context):
        page = context.new_page()
        pbar = tqdm.tqdm(total=MAX_PAGES, desc="Crawling NV DOE")
        while queue and len(seen) < MAX_PAGES:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            pbar.update(1)
            try:
                page.goto(url, wait_until="networkidle", timeout=40000)
                page.wait_for_timeout(2500)
                links = page.eval_on_selector_all(
                    "a[href]", "els=>els.map(a=>({t:a.innerText.trim(), h:a.href}))")
            except Exception as e:
                tqdm.tqdm.write(f"page failed {url}: {e}")
                continue
            for l in links:
                href = l["h"].split("#")[0]
                low = urlparse(href).path.lower()
                if low.endswith(FILE_EXTS):
                    if href not in files:
                        files[href] = {"url": href, "label": l["t"][:120],
                                       "category": _category(l["t"], href), "year": _year(l["t"], href)}
                elif (PAGE_HOST in href and href not in seen and href not in queue
                      and any(k in (l["t"] + href).lower()
                              for k in ["enroll", "financ", "data", "report", "staff",
                                        "licens", "disciplin", "grad", "accountab",
                                        "assessment", "special", "investment", "cte"])):
                    queue.append(href)
            page.wait_for_timeout(800)
        pbar.close()
        browser.close()
    return list(files.values())


import contextlib
from playwright.sync_api import sync_playwright


@contextlib.contextmanager
def sync_playwright_ctx():
    with sync_playwright() as p:
        browser, context = new_browser_context(p, headless=True)
        yield browser, context


def _download(session, item):
    cat = item["category"]
    out_dir = OUT_DIR / cat
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / safe_filename(unquote(Path(urlparse(item["url"]).path).name))
    row = {"state": "NV", "category": cat, "year": item["year"], "label": item["label"],
           "file_url": item["url"], "local_path": str(dest), "status": "", "size_bytes": "", "sha256": ""}
    if dest.exists() and dest.stat().st_size > 0:
        row.update(status="skipped_existing", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
        return row
    with session.get(item["url"], stream=True, timeout=180) as resp:
        if resp.status_code >= 400:
            row["status"] = f"http_{resp.status_code}"
            return row
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    row.update(status="downloaded", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
    return row


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Crawling Nevada DOE data pages (Playwright)...")
    links = crawl_links()
    print(f"Found {len(links)} files")
    from collections import Counter
    print("By category:", dict(Counter(l["category"] for l in links)))

    session = make_session(headers=HEADERS)
    manifest = []
    for item in tqdm.tqdm(links, desc="NV DOE downloads"):
        try:
            manifest.append(_download(session, item))
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {item['url']}: {e}")
            manifest.append({"state": "NV", "category": item["category"], "year": item["year"],
                             "label": item["label"], "file_url": item["url"], "local_path": "",
                             "status": f"error:{str(e)[:50]}", "size_bytes": "", "sha256": ""})
        time.sleep(0.3)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    total = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit())
    print(f"\nDone. {ok}/{len(manifest)} files ({total/1e9:.2f} GB). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
