"""
pa/download.py — Pennsylvania (PDE) Future Ready PA Index data downloader

The Future Ready PA Index publishes per-year Excel datasets at
https://futurereadypa.org/Home/DataFiles via /home/getdatafile?id=<N> links.
Categories: Future Ready Performance Data (PSSA/Keystone proficiency indicators,
on-track/readiness), School Fast Facts and District Fast Facts (enrollment,
demographics, staff), and Fiscal Data (finance). District + school level.

Static HTML → scrape the page for getdatafile links, download each (filename from
the Content-Disposition header), categorize/year from the link label.

NOTE: detailed PSSA/Keystone item-level results live on PA Open Data / data.gov
separately and are a documented extension (see docs/coverage_matrix.md).

Run:
    python scripts/pa/download.py
Environment:
    PA_MIN_YEAR=2018   earliest school-year end to download (default; 0 = all)
"""

import sys
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
from bs4 import BeautifulSoup

from common.file_utils import safe_filename, sha256_file
from common.http_client import make_session
from common.manifest import write_csv

BASE = "https://futurereadypa.org"
DATA_FILES_URL = f"{BASE}/Home/DataFiles"
OUT_DIR = Path("data/raw/pa")
MANIFEST_PATH = OUT_DIR / "manifest.csv"
MIN_YEAR = int(os.environ.get("PA_MIN_YEAR", "2018"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

MANIFEST_FIELDS = [
    "state", "category", "year", "label", "file_url",
    "local_path", "status", "size_bytes", "sha256",
]


def _category(label):
    s = label.lower()
    if "performance" in s:
        return "performance"          # PSSA/Keystone proficiency + readiness indicators
    if "school fast fact" in s:
        return "school_fast_facts"    # enrollment, demographics, staff (school level)
    if "district fast fact" in s:
        return "district_fast_facts"  # enrollment, demographics, staff (district level)
    if "fiscal" in s:
        return "fiscal"               # finance
    return "other"


def _year(label):
    # Labels carry a school year span like "SY 2024-2025" -> end year 2025
    m = re.search(r"(\d{4})\s*[-/]\s*(\d{4})", label)
    if m:
        return int(m.group(2))
    m = re.search(r"(20\d{2})", label)
    return int(m.group(1)) if m else 0


def _filename_from_response(resp, fallback):
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r'filename="?([^";]+)"?', cd)
    return safe_filename(m.group(1)) if m else safe_filename(fallback)


def _get_links(session):
    r = session.get(DATA_FILES_URL, timeout=45)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    links = {}
    for a in soup.select("a[href]"):
        href = a["href"]
        if "getdatafile" not in href.lower():
            continue
        full = urljoin(BASE, href)
        label = a.get_text(" ", strip=True)
        if full not in links:
            links[full] = {
                "url": full, "label": label[:120],
                "category": _category(label), "year": _year(label),
            }
    return list(links.values())


def _download(session, item):
    url = item["url"]
    out_dir = OUT_DIR / item["category"]
    out_dir.mkdir(parents=True, exist_ok=True)

    row = {
        "state": "PA", "category": item["category"], "year": item["year"], "label": item["label"],
        "file_url": url, "local_path": "", "status": "", "size_bytes": "", "sha256": "",
    }
    with session.get(url, stream=True, timeout=180) as resp:
        if resp.status_code >= 400:
            row["status"] = f"http_{resp.status_code}"
            return row
        fallback = f"{item['category']}_{item['year']}.xlsx"
        dest = out_dir / _filename_from_response(resp, fallback)
        row["local_path"] = str(dest)
        if dest.exists() and dest.stat().st_size > 0:
            row.update(status="skipped_existing", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
            return row
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=2 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    row.update(status="downloaded", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
    return row


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)

    print(f"Scraping {DATA_FILES_URL} ...")
    links = _get_links(session)
    print(f"Found {len(links)} data files")
    if MIN_YEAR > 0:
        links = [l for l in links if l["year"] >= MIN_YEAR]
        print(f"Year filter >= {MIN_YEAR}: {len(links)} files")
    from collections import Counter
    print("By category:", dict(Counter(l["category"] for l in links)))

    manifest = []
    for item in tqdm.tqdm(links, desc="PA downloads"):
        try:
            manifest.append(_download(session, item))
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {item['url']}: {e}")
            manifest.append({
                "state": "PA", "category": item["category"], "year": item["year"],
                "label": item["label"], "file_url": item["url"], "local_path": "",
                "status": f"error:{str(e)[:60]}", "size_bytes": "", "sha256": "",
            })
        time.sleep(0.5)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    total = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit())
    print(f"\nDone. {ok}/{len(manifest)} files ({total/1e9:.2f} GB). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
