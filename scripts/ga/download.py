"""
ga/download.py — Georgia (GOSA) bulk education data downloader

The Governor's Office of Student Achievement publishes a flat, static index at
https://download.gosa.ga.gov/ linking ~600 district/school-level data files
(CSV/XLS/XLSX/ZIP) under per-year folders, e.g.
  https://download.gosa.ga.gov/2025/Milestones_EOG_...csv

Covers every target category: assessment (Georgia Milestones EOC/EOG, ACT, SAT,
AP), enrollment, graduation, dropout, finance (revenues/expenditures, salaries,
FESR), personnel/educator qualifications, attendance, discipline, mobility.

Static HTML → parse with requests + BeautifulSoup, categorize by filename,
year from the /YYYY/ path segment, download with skip-existing + sha256 + manifest.

Run:
    python scripts/ga/download.py
Environment:
    GA_MIN_YEAR=2019   only download files for this year and newer (default; 0 = all back to 2004)
"""

import sys
import os
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

BASE = "https://download.gosa.ga.gov/"
OUT_DIR = Path("data/raw/ga")
MANIFEST_PATH = OUT_DIR / "manifest.csv"
FILE_EXTS = (".csv", ".xlsx", ".xls", ".zip")
MIN_YEAR = int(os.environ.get("GA_MIN_YEAR", "2019"))

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


def _category(url, label):
    s = f"{urlparse(url).path} {label}".lower()
    if any(k in s for k in ["milestone", "eoc", "eog", "crct", "eoct", "ghsgt", "ghswt", "egwa", "assessment"]):
        return "assessment_milestones"
    if "act" in s and "attendance" not in s and "contact" not in s:
        return "assessment_act"
    if "sat" in s:
        return "assessment_sat"
    if re.search(r"\bap\b|advanced.?placement", s):
        return "assessment_ap"
    if "enroll" in s:
        return "enrollment"
    if "grad" in s or "completer" in s or "cohort" in s:
        return "graduation"
    if "dropout" in s:
        return "dropout"
    if any(k in s for k in ["financ", "revenue", "expenditure", "salar", "benefit", "fesr", "efficiency"]):
        return "finance"
    if any(k in s for k in ["personnel", "certified", "educator", "inexperienced", "emergency", "out-of-field", "out_of_field", "qualif"]):
        return "personnel_educator"
    if "attendance" in s:
        return "attendance"
    if "disciplin" in s or "conduct" in s:
        return "discipline"
    if "mobility" in s:
        return "mobility"
    if "postsecondary" in s or "hope" in s:
        return "postsecondary"
    if "direct" in s and "cert" in s:
        return "poverty_direct_cert"
    return "other"


def _year(url):
    m = re.search(r"/(\d{4})/", urlparse(url).path)
    return int(m.group(1)) if m else 0


def _get_file_links(session):
    r = session.get(BASE, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    links = {}
    for a in soup.select("a[href]"):
        href = urljoin(BASE, a["href"]).split("#")[0]
        if not urlparse(href).path.lower().endswith(FILE_EXTS):
            continue
        if href in links:
            continue
        label = a.get_text(" ", strip=True)[:120]
        links[href] = {
            "url": href, "label": label,
            "category": _category(href, label), "year": _year(href),
        }
    return list(links.values())


def _download(session, item):
    url = item["url"]
    out_dir = OUT_DIR / item["category"] / str(item["year"])
    out_dir.mkdir(parents=True, exist_ok=True)
    # GOSA filenames repeat across years inside /YYYY/Exports/ — prefix year folder keeps them distinct
    dest = out_dir / safe_filename(Path(urlparse(url).path).name)

    row = {
        "state": "GA", "category": item["category"], "year": item["year"], "label": item["label"],
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
            for chunk in resp.iter_content(chunk_size=2 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    row.update(status="downloaded", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
    return row


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)

    print(f"Scraping {BASE} ...")
    links = _get_file_links(session)
    print(f"Found {len(links)} data files total")

    if MIN_YEAR > 0:
        links = [l for l in links if l["year"] >= MIN_YEAR]
        print(f"Year filter >= {MIN_YEAR}: {len(links)} files (GA_MIN_YEAR=0 for full archive)")

    from collections import Counter
    print("By category:", dict(Counter(l["category"] for l in links)))

    manifest = []
    for item in tqdm.tqdm(links, desc="GA downloads"):
        try:
            manifest.append(_download(session, item))
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {item['url']}: {e}")
            manifest.append({
                "state": "GA", "category": item["category"], "year": item["year"],
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
