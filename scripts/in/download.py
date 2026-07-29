"""
in/download.py — Indiana DOE (IDOE) Data Center bulk files

Indiana publishes its public education data as direct Excel/PDF files under
in.gov/doe/files/, linked from the IDOE Data Center and its archive:

    https://www.in.gov/doe/it/data-center-and-reports/
    https://www.in.gov/doe/it/data-center-and-reports/data-reports-archive/

This is a straightforward static crawl: parse those pages (and any data-center
sub-pages they link to) for /doe/files/*.xlsx|xls|csv|zip|pdf links, then download
each with its link text as the label. in.gov is not bot-gated.

Coverage: assessment (ILEARN grade 3-8 + Biology incl. disaggregated, IREAD, I AM
alternate, SAT, ACT, ECA, participation), enrollment/demographics (by grade,
ethnicity, FRL, gender, SpEd/ELL, corporation + school, back to 2006), attendance
& chronic absenteeism, graduation (state/federal rates, AP, IB), finance (ESSA
school-level financial, school directory), staff (teacher statistics + licensed
teacher reports), and federal accountability ratings.

Discipline/suspension is not published on the IDOE Data Center; it is covered for
Indiana by the federal CRDC pull (scripts/crdc). Interactive EdData / Indiana GPS
dashboards are not crawled (not bulk files).

Output:  data/raw/in/<category>/<filename>
Manifest: data/raw/in/manifest.csv

Run:
    python scripts/in/download.py
"""

import sys
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

BASE = "https://www.in.gov"
SEED_PAGES = [
    "https://www.in.gov/doe/it/data-center-and-reports/",
    "https://www.in.gov/doe/it/data-center-and-reports/data-reports-archive/",
]
OUT_DIR = Path("data/raw/in")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

FILE_EXTS = (".xlsx", ".xls", ".csv", ".zip", ".pdf")
HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")}

MANIFEST_FIELDS = ["state", "category", "label", "file_url", "local_path",
                   "status", "size_bytes", "sha256"]

CATEGORY_KEYWORDS = {
    "assessment": ["ilearn", "iread", "i-am", "i am", "sat", "act", "eca", "assessment",
                   "biology", "participation", "grade3", "grade 3", "wida", "ecattr"],
    "enrollment": ["enrollment", "attendance", "absentee", "transfer", "ethnicity",
                   "gender", "ell", "special-education", "special education", "meal", "membership"],
    "graduation": ["graduation", "grad-rate", "grad rate", "-grad", "cohort", "-ap-",
                   "ap-", "ib-", "baccalaureate", "college", "dropout", "completion"],
    "finance":    ["financial", "finance", "form-9", "form9", "expenditure", "essa",
                   "fiscal", "revenue"],
    "staff":      ["teacher", "licensed", "staff", "educator", "employee-injury", "personnel"],
    "discipline": ["discipline", "suspension", "expulsion"],
}


def _category(label, url):
    hay = (label + " " + url).lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(k in hay for k in kws):
            return cat
    return "other"


def _is_file(href):
    return href and urlparse(href).path.lower().endswith(FILE_EXTS)


def _harvest(session):
    """Crawl seed pages + data-center sub-pages; return {file_url: label}."""
    to_visit = list(SEED_PAGES)
    visited = set()
    files = {}
    while to_visit:
        page_url = to_visit.pop(0)
        if page_url in visited:
            continue
        visited.add(page_url)
        try:
            r = session.get(page_url, timeout=45)
            r.raise_for_status()
        except Exception as e:
            print(f"  page error {page_url}: {str(e)[:60]}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = a["href"]
            full = urljoin(page_url, href)
            label = a.get_text(" ", strip=True)
            if _is_file(full):
                # keep first (usually most descriptive) label seen for a URL
                files.setdefault(full.split("#")[0], label[:150] or Path(urlparse(full).path).stem)
            elif "/doe/it/data-center-and-reports/" in full and full.split("#")[0] not in visited:
                # follow archive / sub-category pages within the data center only
                if full.split("#")[0] not in to_visit:
                    to_visit.append(full.split("#")[0])
    return files


def _download(session, url, label):
    category = _category(label, url)
    fname = safe_filename(unquote(Path(urlparse(url).path).name))
    dest = OUT_DIR / category / fname
    dest.parent.mkdir(parents=True, exist_ok=True)
    row = {"state": "IN", "category": category, "label": label, "file_url": url,
           "local_path": str(dest), "status": "", "size_bytes": "", "sha256": ""}
    if dest.exists() and dest.stat().st_size > 0:
        row.update(status="skipped_existing", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
        return row
    try:
        resp = session.get(url, timeout=180, stream=True)
        if resp.status_code >= 400:
            row["status"] = f"http_{resp.status_code}"
            return row
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        # a broken/incomplete transfer must not abort the whole crawl
        if dest.exists():
            dest.unlink()
        row["status"] = f"error:{str(e)[:60]}"
        return row
    if dest.stat().st_size < 50:
        dest.unlink()
        row["status"] = "too_small"
        return row
    row.update(status="downloaded", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
    return row


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)

    print("Harvesting IDOE data center pages...")
    files = _harvest(session)
    print(f"Total unique files: {len(files)}")

    from collections import Counter
    print("By category:", dict(Counter(_category(l, u) for u, l in files.items()).most_common()))

    manifest = []
    for url, label in tqdm.tqdm(files.items(), desc="IN downloads"):
        manifest.append(_download(session, url, label))
        time.sleep(0.1)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    mb = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit()) / 1e6
    print(f"\nDone. {ok}/{len(manifest)} files ({mb:.1f} MB). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
