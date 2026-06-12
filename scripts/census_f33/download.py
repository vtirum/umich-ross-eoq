"""
census_f33/download.py — Census/NCES district finance (F-33) — financial fill

The U.S. Census Bureau's Annual Survey of School System Finances (the F-33,
also NCES CCD finance) publishes one row per U.S. school district with full
revenue + expenditure detail (72 columns). This is the authoritative district
finance source for every state — a clean universal fill for the "financial"
required category, used here primarily for FL (whose state finance host,
www.fldoe.org, is Akamai-blocked) and as a cross-state finance dataset.

National "individual unit" files: elsec<YY>t.xls per fiscal year. This script
downloads them, then filters per-state rows for the 10 assigned states (by STATE
FIPS code) into data/raw/<ST>/finance_f33/.

Run:
    python scripts/census_f33/download.py
Environment:
    F33_MIN_YEAR=2018   earliest fiscal year (default; files exist ~2010-)
"""

import sys
import os
import csv
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import xlrd
import tqdm

from common.file_utils import sha256_file
from common.http_client import make_session
from common.manifest import write_csv

BASE = "https://www2.census.gov/programs-surveys/school-finances/tables"
OUT_DIR = Path("data/raw/census_f33")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

MIN_YEAR = int(os.environ.get("F33_MIN_YEAR", "2018"))
MAX_YEAR = 2022  # latest published individual-unit file at build time

# Assigned states by Census/FIPS state code (STATE column in the F-33 file).
STATE_FIPS = {"04": "AZ", "06": "CA", "12": "FL", "13": "GA", "25": "MA",
              "26": "MI", "32": "NV", "36": "NY", "42": "PA", "49": "UT"}

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}

MANIFEST_FIELDS = ["year", "file_url", "local_path", "status", "size_bytes", "sha256", "state_rows"]


def _url(year):
    yy = str(year)[2:]
    return f"{BASE}/{year}/secondary-education-finance/elsec{yy}t.xls"


def _download(session, year):
    url = _url(year)
    dest = OUT_DIR / f"elsec{str(year)[2:]}t.xls"
    if dest.exists() and dest.stat().st_size > 0:
        return dest, "skipped_existing"
    with session.get(url, stream=True, timeout=300) as resp:
        if resp.status_code != 200:
            return None, f"http_{resp.status_code}"
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=4 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    return dest, "downloaded"


def _filter_states(xls_path, year):
    """Read the national .xls and write per-state district-finance CSVs.

    State is keyed by FIPS code. Column layout varies by year: newer files have a
    FIPST column; all years have CONUM (county FIPS) or NCESID whose first two
    digits are the state FIPS. We derive the FIPS robustly from whichever exists.
    """
    wb = xlrd.open_workbook(str(xls_path))
    sh = wb.sheet_by_index(0)
    header = [str(sh.cell_value(0, c)) for c in range(sh.ncols)]

    def col(name):
        return header.index(name) if name in header else None

    fipst_i, conum_i, ncesid_i = col("FIPST"), col("CONUM"), col("NCESID")

    def state_fips(row_vals):
        if fipst_i is not None:
            v = str(row_vals[fipst_i]).strip()
            if v and v not in ("N", ""):
                return v.split(".")[0].zfill(2)
        # CONUM = 5-digit county FIPS (SS CCC); NCESID = 7-digit (SS + 5).
        # First 2 digits are the state FIPS in both — pad to the right width.
        for idx, width in ((conum_i, 5), (ncesid_i, 7)):
            if idx is not None:
                v = str(row_vals[idx]).strip().split(".")[0].zfill(width)
                if v[:2].isdigit() and v[:2] != "00":
                    return v[:2]
        return None

    buckets = {st: [] for st in STATE_FIPS.values()}
    for ri in range(1, sh.nrows):
        vals = [sh.cell_value(ri, c) for c in range(sh.ncols)]
        st = STATE_FIPS.get(state_fips(vals) or "")
        if st:
            buckets[st].append(vals)
    written = 0
    for st, rows in buckets.items():
        if not rows:
            continue
        out = Path(f"data/raw/{st.lower()}/finance_f33")
        out.mkdir(parents=True, exist_ok=True)
        dest = out / f"district_finance_f33_{year}.csv"
        with open(dest, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        written += len(rows)
    return written


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)
    years = list(range(MIN_YEAR, MAX_YEAR + 1))
    print(f"Census F-33 district finance — fiscal years {years}")

    manifest = []
    for year in tqdm.tqdm(years, desc="F-33"):
        try:
            path, status = _download(session, year)
            rows = ""
            if path and status in ("downloaded", "skipped_existing"):
                rows = _filter_states(path, year)
            manifest.append({
                "year": year, "file_url": _url(year),
                "local_path": str(path) if path else "", "status": status,
                "size_bytes": path.stat().st_size if path else "",
                "sha256": sha256_file(path) if path else "", "state_rows": rows,
            })
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {year}: {e}")
            manifest.append({"year": year, "file_url": _url(year), "local_path": "",
                             "status": f"error:{str(e)[:50]}", "size_bytes": "",
                             "sha256": "", "state_rows": ""})
        time.sleep(0.5)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    print(f"\nDone. {ok}/{len(manifest)} national files. Per-state finance -> "
          f"data/raw/<ST>/finance_f33/. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
