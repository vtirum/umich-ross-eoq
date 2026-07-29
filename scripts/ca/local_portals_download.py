"""
ca/local_portals_download.py — California Tier-L local/city portals (LAUSD, DataSF, Oakland)

Complements scripts/ca/download.py (statewide CDE) and scripts/ca/assessment_download.py
(CAASPP/ELPAC) with the city/district open-data portals identified in the source
inventory (California_Education_Data_Sources_v2.docx):

  - DataSF (data.sfgov.org) — Socrata. Education-relevant: the "Schools" dataset
    (locations of public/private/community-college sites). SFUSD academic data
    (enrollment/test results) is NOT on DataSF — covered by the statewide CDE files.
  - City of Oakland Open Data (data.oaklandca.gov) — Socrata. Unlike DataSF, Oakland
    hosts genuine OUSD academic-performance datasets under its "Equity Indicators"
    category (Achievement, Enrollment, Teachers/Staffing, Chronic Absenteeism,
    Suspensions, A-G Completion, etc.) — a real OUSD-specific supplement to the
    statewide CDE files.

LAUSD's Open Data Dashboard/Catalog (opendata.lausd.org) requires an authenticated
my.lausd.net / achieve.lausd.net Tableau-style dashboard (similar to GA Insights or
MA's PowerBI accountability dashboard) and is NOT collected here — see
docs/coverage_matrix.md for the deferred network-capture approach.

Both Socrata portals expose a direct CSV export per dataset:
    https://<domain>/resource/<dataset_id>.csv

Run:
    python scripts/ca/local_portals_download.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm

from common.file_utils import safe_filename, sha256_file
from common.http_client import make_session
from common.manifest import write_csv

OUT_DIR = Path("data/raw/ca/local_portals")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

MANIFEST_FIELDS = [
    "state", "portal", "category", "dataset_id", "name",
    "file_url", "local_path", "status", "size_bytes", "sha256",
]

# (domain, portal_label, dataset_id, name, category)
DATASETS = [
    ("data.sfgov.org", "datasf", "7e7j-59qk", "Schools", "school_records"),

    # data.oaklandca.gov "Equity Indicators" category — OUSD academic datasets.
    # Note: several names in this category (Education, Enrollment, Achievement,
    # Program Access, Teachers, Staffing) are Socrata "story" assets — narrative
    # dashboard pages, not downloadable tables — and are excluded below; only the
    # underlying tabular ("dataset" viewType) breakouts are listed.
    ("data.oaklandca.gov", "oakland", "g4fa-34fc", "Preschool Enrollment", "enrollment"),
    ("data.oaklandca.gov", "oakland", "x2vv-6a89", "Representation of Student Population", "enrollment"),
    ("data.oaklandca.gov", "oakland", "5d4q-57a4", "Chronic Absenteeism", "discipline"),
    ("data.oaklandca.gov", "oakland", "r6cm-erzi", "Suspensions", "discipline"),
    ("data.oaklandca.gov", "oakland", "6f7r-23ex", "Disconnected Youth", "discipline"),
    ("data.oaklandca.gov", "oakland", "w6d4-47zb", "3rd Grade ELA Proficiency", "assessment"),
    ("data.oaklandca.gov", "oakland", "46ht-6csa", "A-G Completion (Readiness for UC System)", "assessment"),
    ("data.oaklandca.gov", "oakland", "cjn4-7huj", "High School Readiness", "assessment"),
    ("data.oaklandca.gov", "oakland", "a6x5-ujsk", "Linked Learning Pathway Enrollment", "assessment"),
    ("data.oaklandca.gov", "oakland", "x8wh-yfzv", "Physical Fitness", "assessment"),
    ("data.oaklandca.gov", "oakland", "3rkp-5mtg", "Teacher Experience", "staff"),
    ("data.oaklandca.gov", "oakland", "if52-yyug", "Teacher Turnover", "staff"),
    ("data.oaklandca.gov", "oakland", "sri7-xyr3", "Staffing - Representation", "staff"),
    ("data.oaklandca.gov", "oakland", "5rwp-vgpg", "Attrition from Academy", "staff"),
    ("data.oaklandca.gov", "oakland", "m4xj-firs", "Equal Access Accommodations", "enrollment"),
]


def _download(session, domain, portal, dataset_id, name, category):
    url = f"https://{domain}/resource/{dataset_id}.csv"
    out_dir = OUT_DIR / portal / category
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / safe_filename(f"{name}.csv")

    row = {
        "state": "CA", "portal": portal, "category": category, "dataset_id": dataset_id,
        "name": name, "file_url": url, "local_path": str(dest), "status": "",
        "size_bytes": "", "sha256": "",
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

    manifest = []
    for domain, portal, dataset_id, name, category in tqdm.tqdm(DATASETS, desc="CA local portals"):
        try:
            manifest.append(_download(session, domain, portal, dataset_id, name, category))
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {portal}/{name}: {e}")
            manifest.append({
                "state": "CA", "portal": portal, "category": category, "dataset_id": dataset_id,
                "name": name, "file_url": "", "local_path": "",
                "status": f"error:{str(e)[:60]}", "size_bytes": "", "sha256": "",
            })
        time.sleep(0.3)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    total = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit())
    print(f"\nDone. {ok}/{len(manifest)} files ({total/1e6:.2f} MB). Manifest: {MANIFEST_PATH}")
    print("NOTE: LAUSD's Open Data Dashboard requires authenticated Tableau access — "
          "deferred; see docs/coverage_matrix.md")


if __name__ == "__main__":
    main()
