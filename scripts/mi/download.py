"""
mi/download.py — Michigan (MI School Data / CEPI) static data file downloader

MI School Data serves two kinds of data:
  1. STATIC archive files on the michigan.gov CDN (/-/media/.../MiSchoolData/...) —
     historical assessment zips (MEAP/MME), file layouts, report catalogs. These
     are linked from the data-file pages and downloaded here.
  2. Current M-STEP / enrollment / educator / finance data via an interactive
     "custom dataset builder" dashboard (JS app). That requires dashboard/API
     reverse-engineering (FL-edudata-level) and is NOT covered by this script —
     see docs/coverage_matrix.md (deferred).

This script scrapes the data-file pages for michigan.gov CDN links (which often
lack file extensions) and downloads them with skip-existing + sha256 + manifest.

Run:
    python scripts/mi/download.py
"""

import sys
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
from bs4 import BeautifulSoup

from common.file_utils import safe_filename, sha256_file
from common.http_client import make_session
from common.manifest import write_csv

# All 15 mischooldata.org "*-data-files" pages (discovered by crawling the site
# navigation). Each links Excel/zip files on the michigan.gov CDN (/-/media/).
SEED_PAGES = [
    "https://www.mischooldata.org/k-12-data-files/",
    "https://www.mischooldata.org/historical-assessment-data-files/",
    "https://www.mischooldata.org/college-data-files/",
    # Financial Information Database (FID) — district revenue & expenditure
    "https://www.mischooldata.org/financial-data-files/",
    # Enrollment / pupil counts (the core gap)
    "https://www.mischooldata.org/student-enrollment-counts-data-files7/",
    "https://www.mischooldata.org/district-fte-pupil-counts-data-files/",
    "https://www.mischooldata.org/econdis-counts-data-files/",
    "https://www.mischooldata.org/homeless-enrollment-data-files/",
    "https://www.mischooldata.org/migrant-enrollment-data-files/",
    "https://www.mischooldata.org/nonpublic-student-counts-data-files/",
    "https://www.mischooldata.org/special-education-counts-data-files/",
    "https://www.mischooldata.org/special-education-counts-1-data-files/",
    # Staff / educator (teacher gap)
    "https://www.mischooldata.org/additional-staffing-data-files/",
    # Graduation / dropout
    "https://www.mischooldata.org/graddropout-rates-data-files/",
    # District/school directory
    "https://www.mischooldata.org/districtschool-data-files/",
]

OUT_DIR = Path("data/raw/mi")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

MANIFEST_FIELDS = [
    "state", "category", "year", "label", "file_url",
    "local_path", "status", "size_bytes", "sha256",
]


def _category(url, label):
    s = f"{url} {label}".lower()
    if "financ" in s or "expenditure" in s or "revenue" in s or "fid" in s or "fiscal" in s:
        return "finance"
    if "staffing" in s or "educator" in s or "teacher" in s or "staff" in s:
        return "educator"
    if "assessment" in s or "meap" in s or "mme" in s or "m-step" in s or "mstep" in s \
            or "psat" in s or "wida" in s or ("sat" in s and "satisf" not in s):
        return "assessment"
    if "grad" in s or "dropout" in s:
        return "graduation"
    if "disciplin" in s or "suspension" in s:
        return "discipline"
    if "special education" in s or "special-education" in s or "sped" in s:
        return "special_education"
    if "homeless" in s:
        return "enrollment_homeless"
    if "migrant" in s:
        return "enrollment_migrant"
    if "econdis" in s or "economically" in s:
        return "enrollment_econdis"
    if "nonpublic" in s:
        return "enrollment_nonpublic"
    if "enroll" in s or "count" in s or "fte" in s or "pupil" in s or "membership" in s:
        return "enrollment"
    if "layout" in s or "catalog" in s or "guide" in s or "reference" in s or "directory" in s:
        return "reference"
    if "college" in s or "postsecondary" in s:
        return "postsecondary"
    return "other"


def _year(url, label):
    m = re.search(r"(20\d{2})", f"{url} {label}")
    return int(m.group(1)) if m else 0


def _filename(url, label):
    name = Path(urlparse(url).path).name
    if "." not in name:  # CDN files often lack extensions; default to label/.dat
        base = safe_filename(label or name or "mi_file")
        return f"{base}"
    return safe_filename(name)


def _collect_links(session):
    files = {}
    for page in SEED_PAGES:
        try:
            r = session.get(page, timeout=45)
            r.raise_for_status()
        except Exception as e:
            print(f"  page failed {page}: {e}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = a["href"]
            if "/-/media/" not in href.lower():
                continue
            full = href if href.startswith("http") else urljoin("https://www.michigan.gov", href)
            full = full.split("?")[0] if full.endswith("?rev=") else full
            label = a.get_text(" ", strip=True)
            if full not in files:
                files[full] = {
                    "url": full, "label": label[:120],
                    "category": _category(full, label), "year": _year(full, label),
                }
    return list(files.values())


def _download(session, item):
    url = item["url"]
    out_dir = OUT_DIR / item["category"]
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / _filename(url, item["label"])

    row = {
        "state": "MI", "category": item["category"], "year": item["year"], "label": item["label"],
        "file_url": url, "local_path": str(dest), "status": "", "size_bytes": "", "sha256": "",
    }
    if dest.exists() and dest.stat().st_size > 0:
        row.update(status="skipped_existing", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
        return row
    with session.get(url, stream=True, timeout=300) as resp:
        if resp.status_code >= 400:
            row["status"] = f"http_{resp.status_code}"
            return row
        # Append extension from content-type if filename had none
        ctype = resp.headers.get("content-type", "")
        if "." not in dest.name:
            ext = (".zip" if "zip" in ctype else ".xlsx" if "spreadsheet" in ctype
                   else ".pdf" if "pdf" in ctype else ".csv" if "csv" in ctype else ".dat")
            dest = dest.with_name(dest.name + ext)
            row["local_path"] = str(dest)
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=2 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    row.update(status="downloaded", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
    return row


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)

    print("Collecting MI CDN file links...")
    links = _collect_links(session)
    print(f"Found {len(links)} static files")
    from collections import Counter
    print("By category:", dict(Counter(l["category"] for l in links)))

    manifest = []
    for item in tqdm.tqdm(links, desc="MI downloads"):
        try:
            manifest.append(_download(session, item))
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {item['url']}: {e}")
            manifest.append({
                "state": "MI", "category": item["category"], "year": item["year"],
                "label": item["label"], "file_url": item["url"], "local_path": "",
                "status": f"error:{str(e)[:60]}", "size_bytes": "", "sha256": "",
            })
        time.sleep(0.4)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    total = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit())
    print(f"\nDone. {ok}/{len(manifest)} static files ({total/1e9:.2f} GB). Manifest: {MANIFEST_PATH}")
    print("NOTE: current M-STEP/enrollment/finance data is in MI's interactive builder "
          "(dashboard) — deferred; see docs/coverage_matrix.md")


if __name__ == "__main__":
    main()
