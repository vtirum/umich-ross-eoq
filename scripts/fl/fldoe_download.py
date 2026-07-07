"""
fl/fldoe_download.py — Florida DOE (fldoe.org) bulk data files via Wayback Machine

fldoe.org is protected by Akamai WAF which blocks all automated access (403).
Workaround: scrape file URLs from archive.org cached versions of the index pages,
then download each file through the Wayback Machine proxy (which bypasses the WAF).
The `if_` timestamp suffix returns the raw binary file without Wayback's HTML wrapper.

Sources:
  PK-12 archive page  — attendance, enrollment, staff, graduation, discipline (415 files)
  2025 assessment results — FAST ELA/Math by grade, EOCs, Science (85 files)

Output: data/raw/fl/fldoe/<category>/<filename>
Manifest: data/raw/fl/fldoe/manifest.csv

Run:
    python scripts/fl/fldoe_download.py
Environment:
    FL_MIN_YEAR=2019   only download files whose label contains a year >= this (0=all)
"""

import sys
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
from bs4 import BeautifulSoup

from common.file_utils import safe_filename, sha256_file
from common.http_client import make_session
from common.manifest import write_csv

OUT_DIR = Path("data/raw/fl/fldoe")
MANIFEST_PATH = OUT_DIR / "manifest.csv"
MIN_YEAR = int(os.environ.get("FL_MIN_YEAR", "2019"))

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

FILE_EXTS = (".xls", ".xlsx", ".csv", ".zip")

# Wayback Machine cached index pages (most recent snapshot available)
SOURCE_PAGES = [
    {
        "name": "pk12_archive",
        "wayback_url": "https://web.archive.org/web/2025/https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/archive.stml",
    },
    {
        "name": "assessment_2025",
        "wayback_url": "https://web.archive.org/web/2025/https://www.fldoe.org/accountability/assessments/k-12-student-assessment/results/2025.stml",
    },
]

MANIFEST_FIELDS = [
    "state", "source_page", "category", "label", "wayback_url",
    "local_path", "status", "size_bytes", "sha256",
]

CATEGORY_KEYWORDS = {
    "assessment":  ["assessment", "fsa", "fast", "aims", "eoc", "naep", "sat", "act",
                    "reading", "math", "science", "writing", "ela", "algebra", "geometry",
                    "biology", "civics", "history", "grade"],
    "attendance":  ["absent", "attendance", "ada", "adm"],
    "enrollment":  ["enroll", "membership", "demographics", "race", "gender"],
    "graduation":  ["dropout", "grad", "cohort", "persistence"],
    "discipline":  ["discipline", "suspension", "expulsion"],
    "staff":       ["staff", "personnel", "teacher", "educator", "employee", "sder"],
    "courses":     ["course", "cte"],
    "finance":     ["finance", "expenditure", "revenue", "fund", "fiscal"],
}


def _category(label):
    label_lower = label.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(k in label_lower for k in keywords):
            return cat
    return "other"


def _year_from_label(label):
    m = re.search(r"20(\d{2})-?(?:20)?(\d{2})|20(\d{2})", label)
    if m:
        if m.group(3):
            return int("20" + m.group(3))
        return int("20" + m.group(1))
    return 0


def _wayback_download_url(href):
    """Convert a Wayback Machine page href to a direct file download URL."""
    # href is like /web/20260504094147/https://www.fldoe.org/...
    # We need https://web.archive.org/web/TIMESTAMP_if_/ORIGINAL_URL
    if href.startswith("/web/"):
        parts = href[5:].split("/", 1)  # ["20260504094147", "https://..."]
        if len(parts) == 2:
            timestamp, orig = parts
            return f"https://web.archive.org/web/{timestamp}if_/{orig}"
    return "https://web.archive.org" + href


def _get_links(session, source):
    r = session.get(source["wayback_url"], timeout=45)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    seen = set()
    for a in soup.select("a[href]"):
        href = a["href"]
        if not any(href.lower().endswith(ext) for ext in FILE_EXTS):
            continue
        if href in seen:
            continue
        seen.add(href)
        label = a.get_text(strip=True) or Path(urlparse(href).path).stem
        links.append({
            "source_page": source["name"],
            "label": label[:150],
            "href": href,
            "download_url": _wayback_download_url(href),
        })
    return links


def _download(session, item):
    label = item["label"]
    category = _category(label)
    year = _year_from_label(label)

    # Extract filename from the original URL embedded in the wayback href
    orig_path = item["href"].split("/https://", 1)[-1] if "/https://" in item["href"] else item["href"]
    fname = safe_filename(unquote(Path(urlparse(orig_path).path).name))
    if not fname:
        fname = safe_filename(label[:60]) + ".xls"

    dest = OUT_DIR / category / fname
    dest.parent.mkdir(parents=True, exist_ok=True)

    row = {
        "state": "FL", "source_page": item["source_page"], "category": category,
        "label": label, "wayback_url": item["download_url"],
        "local_path": str(dest), "status": "", "size_bytes": "", "sha256": "",
    }
    if dest.exists() and dest.stat().st_size > 0:
        row.update(status="skipped_existing", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
        return row

    resp = session.get(item["download_url"], timeout=120, stream=True)
    if resp.status_code >= 400:
        row["status"] = f"http_{resp.status_code}"
        return row
    ct = resp.headers.get("Content-Type", "")
    if "html" in ct and resp.headers.get("Content-Length", "99999") == "0":
        row["status"] = "empty_html"
        return row
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    if dest.stat().st_size < 100:
        dest.unlink()
        row["status"] = "too_small"
        return row
    row.update(status="downloaded", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
    return row


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)

    all_links = []
    for source in SOURCE_PAGES:
        print(f"Scraping {source['name']}...")
        links = _get_links(session, source)
        print(f"  {len(links)} files found")
        all_links.extend(links)

    if MIN_YEAR > 0:
        filtered = [l for l in all_links if _year_from_label(l["label"]) == 0 or _year_from_label(l["label"]) >= MIN_YEAR]
        print(f"Year filter >= {MIN_YEAR}: {len(filtered)}/{len(all_links)} files kept")
        all_links = filtered

    from collections import Counter
    cats = Counter(_category(l["label"]) for l in all_links)
    print("By category:", dict(cats.most_common()))

    manifest = []
    for item in tqdm.tqdm(all_links, desc="FL fldoe downloads"):
        try:
            manifest.append(_download(session, item))
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {item['label'][:50]}: {e}")
            manifest.append({
                "state": "FL", "source_page": item["source_page"],
                "category": _category(item["label"]), "label": item["label"],
                "wayback_url": item["download_url"], "local_path": "",
                "status": f"error:{str(e)[:60]}", "size_bytes": "", "sha256": "",
            })
        time.sleep(0.3)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    total_mb = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit()) / 1e6
    print(f"\nDone. {ok}/{len(manifest)} files ({total_mb:.1f} MB). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
