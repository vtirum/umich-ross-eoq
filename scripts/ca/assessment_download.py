"""
ca/assessment_download.py — California assessment (test score) research files

The CDE bulk-data scraper (scripts/ca/download.py) covers enrollment, staff,
graduation, and discipline, but NOT test scores — CA's assessment results live on
a separate ETS-hosted site (caaspp-elpac.ets.org) behind an ASP.NET form whose
on-page links are JS-rendered placeholders.

The actual statewide research files follow a constructable URL pattern:
    https://caaspp-elpac.ets.org/caaspp/researchfiles/<pfx>_ca<year>_all_csv_v<N>.zip
where pfx is the assessment program and "all" = all entities (state + every
district + every school). We probe the version suffix (v1..v4) and download
whichever exists. Each file is fixed-width/CSV with County/District/School codes.

Programs:
  sb   — Smarter Balanced (ELA + Math), grades 3-8 & 11   (2015-)
  caa  — California Alternate Assessments                  (2016-)
  cast — California Science Test                            (2019-)

Run:
    python scripts/ca/assessment_download.py
Environment:
    CA_ASMT_MIN_YEAR=2019   earliest test year (default 2019; 0 = all from 2015)
    CA_ASMT_FORMAT=csv       'csv' (default) or 'ascii' (fixed-width) statewide files
"""

import sys
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm

from common.file_utils import sha256_file
from common.http_client import make_session
from common.manifest import write_csv

BASE = "https://caaspp-elpac.ets.org/caaspp/researchfiles/"
OUT_DIR = Path("data/raw/ca/assessment")
MANIFEST_PATH = OUT_DIR / "assessment_manifest.csv"

MIN_YEAR = int(os.environ.get("CA_ASMT_MIN_YEAR", "2019"))
FMT = os.environ.get("CA_ASMT_FORMAT", "csv")  # csv or ascii
MAX_VERSION = 5

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}

# program prefix -> (label, first year)
PROGRAMS = {
    "sb":   ("smarter_balanced_ela_math", 2015),
    "caa":  ("alternate_assessment", 2016),
    "cast": ("science_cast", 2019),
}

CURRENT_YEAR = 2025

MANIFEST_FIELDS = [
    "state", "program", "year", "version", "file_url",
    "local_path", "status", "size_bytes", "sha256",
]


def _try_download(session, pfx, label, year):
    """Probe version suffixes and download the statewide all-entities file for a year."""
    out_dir = OUT_DIR / label
    out_dir.mkdir(parents=True, exist_ok=True)

    for v in range(1, MAX_VERSION + 1):
        fname = f"{pfx}_ca{year}_all_{FMT}_v{v}.zip"
        url = BASE + fname
        dest = out_dir / fname

        if dest.exists() and dest.stat().st_size > 0:
            return {
                "state": "CA", "program": label, "year": year, "version": v,
                "file_url": url, "local_path": str(dest), "status": "skipped_existing",
                "size_bytes": dest.stat().st_size, "sha256": sha256_file(dest),
            }

        with session.get(url, stream=True, timeout=300) as resp:
            if resp.status_code != 200:
                continue
            clen = int(resp.headers.get("content-length", 0))
            if clen and clen < 1000:  # tiny = error stub, not a real file
                continue
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=4 * 1024 * 1024):
                    if chunk:
                        f.write(chunk)
        return {
            "state": "CA", "program": label, "year": year, "version": v,
            "file_url": url, "local_path": str(dest), "status": "downloaded",
            "size_bytes": dest.stat().st_size, "sha256": sha256_file(dest),
        }

    # No version found for this year
    return {
        "state": "CA", "program": label, "year": year, "version": "",
        "file_url": BASE + f"{pfx}_ca{year}_all_{FMT}_v*.zip", "local_path": "",
        "status": "not_available", "size_bytes": "", "sha256": "",
    }


def _download_lookup(session, pfx, label, year):
    """Entity lookup file (maps County/District/School codes to names), once per year."""
    fname = f"{pfx}_ca{year}entities_{FMT}.zip"
    url = BASE + fname
    out_dir = OUT_DIR / label
    dest = out_dir / fname
    if dest.exists() and dest.stat().st_size > 0:
        return None
    with session.get(url, stream=True, timeout=120) as resp:
        if resp.status_code != 200:
            return None
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return {
        "state": "CA", "program": label, "year": year, "version": "entities",
        "file_url": url, "local_path": str(dest), "status": "downloaded",
        "size_bytes": dest.stat().st_size, "sha256": sha256_file(dest),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=HEADERS)

    start_year = MIN_YEAR if MIN_YEAR > 0 else 2015
    tasks = []
    for pfx, (label, first_year) in PROGRAMS.items():
        for year in range(max(start_year, first_year), CURRENT_YEAR + 1):
            tasks.append((pfx, label, year))

    print(f"CA assessment: {len(tasks)} program-years (format={FMT}, years {start_year}-{CURRENT_YEAR})")

    manifest = []
    for pfx, label, year in tqdm.tqdm(tasks, desc="CA assessment"):
        try:
            row = _try_download(session, pfx, label, year)
            manifest.append(row)
            if row["status"] in ("downloaded", "skipped_existing"):
                lk = _download_lookup(session, pfx, label, year)
                if lk:
                    manifest.append(lk)
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {pfx} {year}: {e}")
            manifest.append({
                "state": "CA", "program": label, "year": year, "version": "",
                "file_url": "", "local_path": "", "status": f"error:{str(e)[:50]}",
                "size_bytes": "", "sha256": "",
            })
        time.sleep(0.5)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    got = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    na = sum(1 for r in manifest if r["status"] == "not_available")
    total = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit())
    print(f"\nDone. {got} files ({total/1e9:.2f} GB), {na} program-years unavailable. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
