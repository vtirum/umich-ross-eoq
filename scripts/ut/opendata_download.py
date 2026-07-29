"""
ut/opendata_download.py — Utah Open Data (opendata.utah.gov) USBE-owned datasets

Complements scripts/ut/download.py (USBE static reports.php files) with Utah's
statewide open-data catalog, identified in the source inventory
(Utah_Education_Data_Sources_v2.docx) as the only Tier-L ("local/alternative")
source for Utah — the state is unusually centralized, so no city or district runs
its own K-12 portal. opendata.utah.gov is a Socrata catalog that re-serves USBE
figures (often historical district/school-level breakouts, e.g. per-district
graduation-rate datasets, that aren't broken out that way in the bulk reports.php
files) with CSV/API access.

Two phases:
  1. Query the Socrata catalog API for the "Education" category, filtered to
     datasets whose `Dataset-Information_Agency` metadata is "State Office of
     Education" (i.e. actually owned/published by USBE, not Higher Ed/Census/etc).
  2. Download each via the Socrata CSV export endpoint
     (https://opendata.utah.gov/resource/<id>.csv).

Run:
    python scripts/ut/opendata_download.py
"""

import sys
import re
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm

from common.file_utils import safe_filename, sha256_file
from common.http_client import make_session
from common.manifest import write_csv

CATALOG_API = "https://opendata.utah.gov/api/catalog/v1"
DOMAIN = "opendata.utah.gov"
AGENCY = "State Office of Education"
OUT_DIR = Path("data/raw/ut/opendata")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

MANIFEST_FIELDS = [
    "state", "category", "year", "dataset_id", "name",
    "file_url", "local_path", "status", "size_bytes", "sha256",
]


def _agency(res):
    for m in res["classification"].get("domain_metadata", []):
        if m["key"] == "Dataset-Information_Agency":
            return m["value"]
    return None


def _category(name):
    s = name.lower()
    if "graduation" in s or "dropout" in s:
        return "graduation"
    if "salary" in s or "financ" in s or "expenditure" in s or "revenue" in s:
        return "finance"
    if "teacher" in s or "educator" in s or "administrator" in s or "staff" in s:
        return "staff"
    if "discipl" in s or "suspension" in s or "expulsion" in s:
        return "discipline"
    if "test" in s or "sage" in s or "rise" in s or "assess" in s or "act " in s or "proficien" in s:
        return "assessment"
    if "enroll" in s or "membership" in s or "address list" in s or "school grade" in s:
        return "enrollment"
    return "other"


def _year(name):
    m = re.search(r"(20\d{2})", name)
    return int(m.group(1)) if m else 0


def discover_datasets(session):
    """Page through the Education category, keep only USBE-owned datasets."""
    items = {}
    offset = 0
    while True:
        r = session.get(CATALOG_API, params={
            "domains": DOMAIN, "search_context": DOMAIN,
            "categories": "Education", "limit": 100, "offset": offset,
        }, timeout=30)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            break
        for res in results:
            if _agency(res) != AGENCY:
                continue
            rid = res["resource"]["id"]
            if res["resource"].get("type") != "dataset":
                continue
            name = res["resource"]["name"]
            if rid not in items:
                items[rid] = {
                    "id": rid, "name": name,
                    "category": _category(name), "year": _year(name),
                }
        offset += 100
        if offset > 5000:
            break
    return list(items.values())


def _download(session, item):
    url = f"https://{DOMAIN}/resource/{item['id']}.csv"
    out_dir = OUT_DIR / item["category"]
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / safe_filename(f"{item['name']}_{item['id']}.csv")

    row = {
        "state": "UT", "category": item["category"], "year": item["year"],
        "dataset_id": item["id"], "name": item["name"], "file_url": url,
        "local_path": str(dest), "status": "", "size_bytes": "", "sha256": "",
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

    print("Discovering USBE-owned datasets in the opendata.utah.gov Education category...")
    items = discover_datasets(session)
    print(f"Found {len(items)} USBE datasets")
    from collections import Counter
    print("By category:", dict(Counter(i["category"] for i in items)))

    manifest = []
    for item in tqdm.tqdm(items, desc="UT opendata downloads"):
        try:
            manifest.append(_download(session, item))
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {item['name']}: {e}")
            manifest.append({
                "state": "UT", "category": item["category"], "year": item["year"],
                "dataset_id": item["id"], "name": item["name"], "file_url": "",
                "local_path": "", "status": f"error:{str(e)[:60]}", "size_bytes": "", "sha256": "",
            })
        time.sleep(0.2)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    total = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit())
    print(f"\nDone. {ok}/{len(manifest)} files ({total/1e6:.2f} MB). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
