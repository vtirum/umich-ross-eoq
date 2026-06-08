"""
ut/download.py — Utah (USBE) statistical reports downloader

Utah's primary public data lives in two places:
  1. STATIC reports at schools.utah.gov/datastatistics/reports.php — ~307 Excel/PDF
     files under /_datastatisticsfiles_/_reports_/_<category>_/, covering
     assessments, enrollment/membership, educators, graduation/dropout, class
     size, child nutrition, and schools. This script collects those.
  2. The interactive "Data Gateway" (datagateway.schools.utah.gov), a public
     Tableau portal (tableau.com/t/usbedata/views/...). NOT collected here — the
     static reports already cover the target categories; the Tableau dashboards
     are a documented optional add-on (same Embedding-API approach as FL edudata).

Static HTML index → parse links, categorize by URL path, year from filename/text,
download with skip-existing + sha256 + manifest.

Run:
    python scripts/ut/download.py
Environment:
    UT_MIN_YEAR=2019   only download files whose parsed year >= this (default; 0 = all)
"""

import sys
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
from bs4 import BeautifulSoup

from common.file_utils import safe_filename, sha256_file
from common.http_client import make_session
from common.manifest import write_csv

BASE = "https://schools.utah.gov"
REPORTS_URL = f"{BASE}/datastatistics/reports.php"
OUT_DIR = Path("data/raw/ut")
MANIFEST_PATH = OUT_DIR / "manifest.csv"
FILE_EXTS = (".xlsx", ".xls", ".csv", ".zip", ".pdf")
MIN_YEAR = int(os.environ.get("UT_MIN_YEAR", "2019"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

# raw path segment -> clean category
CATEGORY_MAP = {
    "assessments": "assessment",
    "enrollmentmembership": "enrollment",
    "educators": "educator_staff",
    "graduationdropoutrates": "graduation_dropout",
    "classsize": "class_size",
    "cnpnslp": "child_nutrition",
    "schools": "schools",
    "researchreports": "research",
}

MANIFEST_FIELDS = [
    "state", "category", "year", "label", "file_url",
    "local_path", "status", "size_bytes", "sha256",
]


def _category(url):
    m = re.search(r"_reports_/_([^/]+)_/", url)
    raw = m.group(1) if m else "other"
    return CATEGORY_MAP.get(raw, raw)


def _year(url, label):
    m = re.search(r"(20\d{2})", f"{label} {unquote(url)}")
    return int(m.group(1)) if m else 0


def _get_file_links(session):
    r = session.get(REPORTS_URL, timeout=45)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    links = {}
    for a in soup.select("a[href]"):
        href = a["href"]
        if not urlparse(href).path.lower().endswith(FILE_EXTS):
            continue
        full = urljoin(BASE, href)
        if full in links:
            continue
        label = a.get_text(" ", strip=True)
        links[full] = {
            "url": full, "label": label[:120],
            "category": _category(full), "year": _year(full, label),
        }
    return list(links.values())


def _download(session, item):
    url = item["url"]
    out_dir = OUT_DIR / item["category"] / (str(item["year"]) if item["year"] else "undated")
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / safe_filename(unquote(Path(urlparse(url).path).name))

    row = {
        "state": "UT", "category": item["category"], "year": item["year"], "label": item["label"],
        "file_url": url, "local_path": str(dest), "status": "", "size_bytes": "", "sha256": "",
    }
    if dest.exists() and dest.stat().st_size > 0:
        row.update(status="skipped_existing", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
        return row
    with session.get(url, stream=True, timeout=180) as resp:
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
    session = make_session(headers=HEADERS)

    print(f"Scraping {REPORTS_URL} ...")
    links = _get_file_links(session)
    print(f"Found {len(links)} files")
    if MIN_YEAR > 0:
        links = [l for l in links if l["year"] == 0 or l["year"] >= MIN_YEAR]
        print(f"Year filter >= {MIN_YEAR} (undated kept): {len(links)} files")
    from collections import Counter
    print("By category:", dict(Counter(l["category"] for l in links)))

    manifest = []
    for item in tqdm.tqdm(links, desc="UT downloads"):
        try:
            manifest.append(_download(session, item))
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {item['url']}: {e}")
            manifest.append({
                "state": "UT", "category": item["category"], "year": item["year"],
                "label": item["label"], "file_url": item["url"], "local_path": "",
                "status": f"error:{str(e)[:60]}", "size_bytes": "", "sha256": "",
            })
        time.sleep(0.3)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    total = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit())
    print(f"\nDone. {ok}/{len(manifest)} files ({total/1e9:.2f} GB). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
