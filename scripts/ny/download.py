"""
ny/download.py — New York (NYSED) bulk education data downloader

NYSED publishes everything as per-year zipped databases at
https://data.nysed.gov/downloads.php — the single cleanest source of the 10
states. Each year's "Report Card Database" (SRC*.zip, MS Access) contains
assessment (ELA/Math/Science/Regents), enrollment, graduation, staff
qualifications, attendance, suspensions, and per-pupil expenditures at state,
district, and school levels. Additional per-domain databases (enrollment,
graduation, assessment, student+educator, AP/IB, ELL, teacher evaluation,
pathways) are also published.

This script scrapes the downloads page, categorizes each file by its URL path,
parses its year, filters by a configurable minimum year, downloads with
skip-if-exists + sha256 + manifest, and optionally unzips each archive.

Run:
    python scripts/ny/download.py

Environment:
    NY_MIN_YEAR=2019   only download files for this end-year and newer (default)
                       set NY_MIN_YEAR=0 to download the full archive (back to 1999)
    NY_UNZIP=0         extract each downloaded zip alongside it (default OFF —
                       the Access DBs decompress ~10x; keep the portable zips and
                       extract later as a cleaning step. Set NY_UNZIP=1 to extract.)
"""

import sys
import os
import re
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
from bs4 import BeautifulSoup

from common.file_utils import safe_filename, sha256_file
from common.http_client import make_session
from common.manifest import write_csv

BASE = "https://data.nysed.gov"
DOWNLOADS_URL = f"{BASE}/downloads.php"
OUT_DIR = Path("data/raw/ny")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

MIN_YEAR = int(os.environ.get("NY_MIN_YEAR", "2019"))
UNZIP = os.environ.get("NY_UNZIP", "0") not in ("0", "false", "no", "")

# Browser UA — data.nysed.gov is tolerant but use a real UA for consistency.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Map a URL path segment to a clean category name.
CATEGORY_BY_SEGMENT = {
    "essa": "report_card",
    "reportcards": "report_card",
    "enrollment": "enrollment",
    "gradrate": "graduation_rate",
    "assessment": "assessment_3_8",
    "studed": "student_educator",
    "apib": "ap_ib",
    "ell": "english_learners",
    "eval": "teacher_evaluation",
    "pathways": "graduation_pathways",
    "student-digital-resources": "digital_resources",
}

MANIFEST_FIELDS = [
    "state", "category", "year", "label", "file_url",
    "local_path", "status", "size_bytes", "sha256", "extracted_to",
]

FILE_EXTS = (".zip", ".xlsx", ".xls", ".csv", ".mdb", ".accdb")


def _category(url):
    parts = urlparse(url).path.lower().split("/")
    for seg in parts:
        if seg in CATEGORY_BY_SEGMENT:
            return CATEGORY_BY_SEGMENT[seg]
    return "other"


def _year(url):
    """Extract the data end-year. Filenames carry it (SRC2025, APIB24, ENROLLMENT_2025);
    fall back to the YY-YY path segment."""
    name = Path(urlparse(url).path).name
    # 4-digit year in filename (e.g. SRC2025, enrollment_2024)
    m = re.search(r"(19|20)\d{2}", name)
    if m:
        return int(m.group(0))
    # 2-digit year in filename (e.g. APIB24)
    m = re.search(r"[A-Za-z](\d{2})\.", name)
    if m:
        return 2000 + int(m.group(1))
    # YY-YY path segment (e.g. /24-25/) -> end year
    m = re.search(r"/(\d{2})-(\d{2})/", urlparse(url).path)
    if m:
        return 2000 + int(m.group(2))
    return 0


def _get_file_links(session):
    resp = session.get(DOWNLOADS_URL, timeout=60)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    links = []
    seen = set()
    for a in soup.select("a[href]"):
        href = urljoin(BASE, a["href"])
        if not urlparse(href).path.lower().endswith(FILE_EXTS):
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append({
            "url": href,
            "label": " ".join(a.get_text(" ", strip=True).split()),
            "category": _category(href),
            "year": _year(href),
        })
    return links


def _download(session, item):
    url = item["url"]
    category = item["category"]
    year = item["year"]

    out_dir = OUT_DIR / category / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(Path(urlparse(url).path).name)
    dest = out_dir / filename

    row = {
        "state": "NY", "category": category, "year": year, "label": item["label"],
        "file_url": url, "local_path": str(dest), "status": "", "size_bytes": "",
        "sha256": "", "extracted_to": "",
    }

    if dest.exists() and dest.stat().st_size > 0:
        row.update(status="skipped_existing", size_bytes=dest.stat().st_size,
                   sha256=sha256_file(dest))
    else:
        with session.get(url, stream=True, timeout=300) as resp:
            if resp.status_code >= 400:
                row["status"] = f"http_{resp.status_code}"
                return row
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=4 * 1024 * 1024):
                    if chunk:
                        f.write(chunk)
        row.update(status="downloaded", size_bytes=dest.stat().st_size,
                   sha256=sha256_file(dest))

    if UNZIP and dest.suffix.lower() == ".zip":
        extract_dir = out_dir / dest.stem
        try:
            if not extract_dir.exists():
                with zipfile.ZipFile(dest) as zf:
                    zf.extractall(extract_dir)
            row["extracted_to"] = str(extract_dir)
        except zipfile.BadZipFile:
            row["extracted_to"] = "bad_zip"

    return row


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)

    print(f"Scraping {DOWNLOADS_URL} ...")
    links = _get_file_links(session)
    print(f"Found {len(links)} files total")

    if MIN_YEAR > 0:
        links = [l for l in links if l["year"] >= MIN_YEAR]
        print(f"Filtered to year >= {MIN_YEAR}: {len(links)} files "
              f"(set NY_MIN_YEAR=0 for full archive)")

    # Largest report-card DBs last so quicker wins land first
    links.sort(key=lambda l: (l["category"] != "report_card", -l["year"]))

    manifest = []
    for item in tqdm.tqdm(links, desc="NY downloads"):
        try:
            manifest.append(_download(session, item))
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {item['url']}: {e}")
            manifest.append({
                "state": "NY", "category": item["category"], "year": item["year"],
                "label": item["label"], "file_url": item["url"], "local_path": "",
                "status": f"error:{str(e)[:60]}", "size_bytes": "", "sha256": "",
                "extracted_to": "",
            })
        time.sleep(0.5)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    total_bytes = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit())
    print(f"\nDone. {ok}/{len(manifest)} files ({total_bytes/1e9:.2f} GB). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
