"""
ma/infoservices_download.py — Massachusetts (DESE) InfoServices bulk report files

doe.mass.edu/infoservices/reports/ is a separate static-file archive from
profiles.doe.mass.edu/statereport (already covered by scripts/ma/download.py).
It hosts per-year bulk Excel downloads (district + school level) for:

  enroll/      — regular enrollment (yr=2017..2026), special ed enrollment
                 (yr=sped2017..sped2026), and CVTE enrollment (yr=cvte1617..cvte2122)
  attendance/  — attendance by grade/student-group, mid-year + end-of-year
  bullying/    — bullying allegations (SY23-SY25)
  retention/   — in-grade retention (Appendix A/B)
  enroll_ihe/  — postsecondary (IHE) enrollment outcomes
  gradrates/   — statewide graduation trend file

Each hub page is scraped for spreadsheet links (.xlsx/.xls/.csv/.pdf) and the
files are downloaded with skip-existing + sha256 + manifest, same pattern as
the other state scripts.

Run:
    python scripts/ma/infoservices_download.py
"""

import sys
import re
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
from bs4 import BeautifulSoup

from common.file_utils import FILE_EXTS, safe_filename, sha256_file
from common.http_client import make_session
from common.manifest import write_csv

BASE = "https://www.doe.mass.edu"
OUT_DIR = Path("data/raw/ma/infoservices")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

MANIFEST_FIELDS = [
    "state", "category", "report", "page", "label", "file_url",
    "local_path", "status", "size_bytes", "sha256",
]

# Regular enrollment years 2017-2026
ENROLL_PAGES = [(f"enroll/default.html?yr={y}", "enrollment", "enrollment") for y in range(2017, 2027)]
# Special ed enrollment 2017-2026
ENROLL_PAGES += [(f"enroll/default.html?yr=sped{y}", "enrollment", "enrollment_sped") for y in range(2017, 2027)]
# CVTE enrollment
CVTE_CODES = ["cvte1617", "cvte1718", "cvte1819", "cvte1920", "cvte2021", "cvte2122"]
ENROLL_PAGES += [(f"enroll/default.html?yr={c}", "enrollment", "enrollment_cvte") for c in CVTE_CODES]

# Other report hubs (single page each, files cover multiple years)
OTHER_PAGES = [
    ("infoservices/reports/attendance/default.html", "attendance", "attendance"),
    ("infoservices/reports/bullying/default.html", "discipline", "bullying"),
    ("infoservices/reports/retention/default.html", "retention", "retention"),
    ("infoservices/reports/enroll_ihe/default.html", "postsecondary", "enroll_ihe"),
    ("infoservices/reports/gradrates/default.html", "graduation", "gradrates"),
]


def _collect_links(session, page_path, category, report):
    if page_path.startswith("infoservices/"):
        url = f"{BASE}/{page_path}"
    else:
        url = f"{BASE}/infoservices/reports/{page_path}"
    try:
        r = session.get(url, timeout=45)
        r.raise_for_status()
    except Exception as e:
        print(f"  page failed {url}: {e}")
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    items = []
    for a in soup.select("a[href]"):
        href = a["href"]
        if not re.search(r"\.(xlsx|xls|csv|pdf|zip)$", href, re.I):
            continue
        full = urljoin(url, href)
        label = a.get_text(" ", strip=True)
        items.append({
            "category": category, "report": report, "page": page_path,
            "label": label[:120], "url": full,
        })
    return items


def _filename(item):
    name = Path(item["url"].split("?")[0]).name
    # CVTE/enroll filenames repeat across years/report types — prefix with the
    # page's "yr" value (or a cleaned slug for single-page hubs) for uniqueness.
    m = re.search(r"yr=([A-Za-z0-9]+)", item["page"])
    page_tag = m.group(1) if m else re.sub(r"[^A-Za-z0-9]+", "_", item["page"].split("/")[-2] or item["page"]).strip("_")
    return safe_filename(f"{item['report']}_{page_tag}_{name}")


def _download(session, item):
    out_dir = OUT_DIR / item["category"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / _filename(item)
    row = {
        "state": "MA", "category": item["category"], "report": item["report"],
        "page": item["page"], "label": item["label"], "file_url": item["url"],
        "local_path": str(out_path), "status": "", "size_bytes": "", "sha256": "",
    }
    if out_path.exists():
        row["status"] = "skipped_existing"
        row["size_bytes"] = out_path.stat().st_size
        row["sha256"] = sha256_file(out_path)
        return row
    try:
        r = session.get(item["url"], timeout=120, stream=True)
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
        row["status"] = "downloaded"
        row["size_bytes"] = out_path.stat().st_size
        row["sha256"] = sha256_file(out_path)
    except Exception as e:
        row["status"] = f"error: {e}"
        if out_path.exists():
            out_path.unlink()
    return row


def main():
    session = make_session(HEADERS)
    print("Collecting MA InfoServices file links...")
    all_items = []
    for page_path, category, report in ENROLL_PAGES + OTHER_PAGES:
        items = _collect_links(session, page_path, category, report)
        print(f"  {page_path}: {len(items)} files")
        all_items.extend(items)

    print(f"Total files: {len(all_items)}")
    rows = []
    for item in tqdm.tqdm(all_items, desc="MA InfoServices downloads"):
        rows.append(_download(session, item))

    write_csv(MANIFEST_PATH, rows, MANIFEST_FIELDS)
    statuses = {}
    for r in rows:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    print("Status summary:", statuses)


if __name__ == "__main__":
    main()
