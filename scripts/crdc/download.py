"""
crdc/download.py — Federal Civil Rights Data Collection (discipline fill, all states)

Several state DOEs don't publish school-level discipline/suspension data in a
scrapable form (AZ, GA, PA; FL's host is WAF-blocked). The U.S. Dept. of Education
Office for Civil Rights publishes the CRDC — a biennial, school-level public-use
dataset covering EVERY public school in the country, including:
  - Suspensions (in/out of school), Expulsions, Corporal punishment
  - Restraint & Seclusion, School-related arrests, Referrals to law enforcement
  - plus enrollment, AP/IB, teachers/staff, chronic absenteeism

One national zip per collection year. Each contains CSVs with an `LEA_STATE`
column, so the assigned states (AZ FL CA UT NV MA NY GA PA MI) are recoverable
by simple filtering. This is the universal fill for the "suspensions/discipline"
required category.

Run:
    python scripts/crdc/download.py
Environment:
    CRDC_INCLUDE_2122=1   also fetch the 2021-22 file (832 MB; off by default)
    CRDC_FILTER_STATES=1  after download, extract per-state discipline CSVs for
                          the assigned states into data/raw/<ST>/discipline_crdc/
"""

import sys
import os
import csv
import io
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm

from common.file_utils import sha256_file
from common.http_client import make_session
from common.manifest import write_csv

BASE = "https://civilrightsdata.ed.gov/assets/ocr/docs/"
OUT_DIR = Path("data/raw/crdc")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

# Modest files by default; the 832 MB 2021-22 file is opt-in.
YEARS = ["2015-16", "2017-18", "2020-21"]
if os.environ.get("CRDC_INCLUDE_2122", "0") not in ("0", "false", "no", ""):
    YEARS = ["2015-16", "2017-18", "2020-21", "2021-22"]

FILTER_STATES = os.environ.get("CRDC_FILTER_STATES", "1") not in ("0", "false", "no", "")

# Assigned states — 2-letter postal codes used in the CRDC LEA_STATE column.
ASSIGNED = {"AZ", "FL", "CA", "UT", "NV", "MA", "NY", "GA", "PA", "MI"}

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}

# CRDC CSV name keyword -> destination category. The national files carry far
# more than discipline; extracting these gives multi-category coverage (esp. for
# the dashboard-gated states MI/NV and the WAF-blocked FL).
CRDC_CATEGORY_KEYWORDS = {
    "discipline": ["suspension", "expulsion", "restraint", "corporal",
                   "referral", "arrest", "discipline", "offense", "harassment"],
    "enrollment": ["enrollment"],
    "staff":      ["school characteristics", "school support", "teacher"],
    "assessment": ["sat and act", "advanced placement", "international baccalaureate"],
}

MANIFEST_FIELDS = ["year", "file_url", "local_path", "status", "size_bytes", "sha256"]


def _download_year(session, year):
    url = f"{BASE}{year}-crdc-data.zip"
    dest = OUT_DIR / f"{year}-crdc-data.zip"
    row = {"year": year, "file_url": url, "local_path": str(dest),
           "status": "", "size_bytes": "", "sha256": ""}
    if dest.exists() and dest.stat().st_size > 0:
        row.update(status="skipped_existing", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
        return row
    with session.get(url, stream=True, timeout=600) as resp:
        if resp.status_code != 200:
            row["status"] = f"http_{resp.status_code}"
            return row
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    row.update(status="downloaded", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
    return row


def _filter_states(year):
    """Extract discipline CSVs from a year's zip, writing per-state rows for the
    assigned states into data/raw/<ST>/discipline_crdc/<csvname>_<year>.csv."""
    zip_path = OUT_DIR / f"{year}-crdc-data.zip"
    if not zip_path.exists():
        return 0
    written = 0
    with zipfile.ZipFile(zip_path) as zf:
        # match each CSV to a destination category by name keyword
        members = []
        for n in zf.namelist():
            if not n.lower().endswith(".csv"):
                continue
            ln = Path(n).stem.lower()
            cat = next((c for c, kws in CRDC_CATEGORY_KEYWORDS.items()
                        if any(k in ln for k in kws)), None)
            if cat:
                members.append((n, cat))
        for name, cat in members:
            try:
                raw = zf.read(name)
            except Exception:
                continue
            text = raw.decode("latin-1")
            reader = csv.reader(io.StringIO(text))
            try:
                header = next(reader)
            except StopIteration:
                continue
            # find the state column
            state_idx = next((i for i, h in enumerate(header)
                              if h.strip().upper() in ("LEA_STATE", "STATE", "LEASTATE")), None)
            if state_idx is None:
                continue
            buckets = {st: [] for st in ASSIGNED}
            for r in reader:
                if state_idx < len(r) and r[state_idx].strip().upper() in ASSIGNED:
                    buckets[r[state_idx].strip().upper()].append(r)
            base = Path(name).stem
            for st, rows in buckets.items():
                if not rows:
                    continue
                out = Path(f"data/raw/{st.lower()}/{cat}_crdc")
                out.mkdir(parents=True, exist_ok=True)
                dest = out / f"{base}_{year}.csv"
                with open(dest, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(header)
                    w.writerows(rows)
                written += 1
    return written


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)

    print(f"CRDC national discipline data — years: {YEARS}")
    manifest = []
    for year in tqdm.tqdm(YEARS, desc="CRDC download"):
        try:
            manifest.append(_download_year(session, year))
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {year}: {e}")
            manifest.append({"year": year, "file_url": f"{BASE}{year}-crdc-data.zip",
                             "local_path": "", "status": f"error:{str(e)[:50]}",
                             "size_bytes": "", "sha256": ""})
        time.sleep(0.5)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    got = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    total = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit())
    print(f"\nDownloaded {got}/{len(manifest)} national files ({total/1e9:.2f} GB).")

    if FILTER_STATES:
        print("\nExtracting per-state discipline CSVs for assigned states...")
        for year in tqdm.tqdm(YEARS, desc="Filter states"):
            n = _filter_states(year)
            tqdm.tqdm.write(f"  {year}: wrote {n} per-state discipline CSVs")
        print("Per-state discipline written to data/raw/<ST>/discipline_crdc/")

    print(f"\nDone. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
