"""
mn/mde_analytics_files.py — MDE Analytics bulk data files (pub.education.mn.gov)

The MDE Analytics portal (pub.education.mn.gov/MDEAnalytics/Data.jsp) has ~59 data
topics. They come in two flavors:

  1. FILE-LISTING topics (e.g. "Assessment Files", TOPICID=1) — dropdown filters
     plus a "List files" button that renders a table of downloadable files. The
     files themselves are served from education.mn.gov's content server:
         https://education.mn.gov/mdeprod/idcplg?IdcService=GET_FILE
             &RevisionSelectionMethod=latestReleased&Rendition=primary&dDocName=<ID>
     That host is NOT bot-protected, so files download with plain requests.
  2. REPORT-RUNNER topics — interactive WebFOCUS reports (Run Report/Download).
     pub.education.mn.gov guards those with PerimeterX; not handled here.

This script covers flavor 1. The "List files" form POSTs to WFServlet.ibfs and
renders results in a nested iframe; we replicate that POST directly (with the
listing page as Referer) and parse the resulting HTML table, capturing each file's
metadata columns (e.g. Test Name / Year / Public-Nonpublic / Subject / Grade) plus
its download link, then fetch every file.

Assessment Files alone yields ~600 files, 1998-2025: MCA, MTAS, Alt-MCA, MOD, GRAD,
BST, ACCESS / Alternate ACCESS, TEAE, MTELL, SOLOM, WIDA — at state, county,
district and school level, disaggregated by student group (race/ethnicity, gender,
special education, English learner, free/reduced-price meals) subject to MDE's
small-N privacy suppression.

Output:  data/raw/mn/mde_analytics/<topic>/<filename>
Manifest: data/raw/mn/mde_analytics/manifest.csv

Run:
    python scripts/mn/mde_analytics_files.py
Environment:
    MN_TOPICS=1,4,133   restrict to specific TOPICIDs (default: all known file-listing topics)
"""

import sys
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

from common.file_utils import safe_filename, sha256_file
from common.manifest import write_csv

BASE = "https://pub.education.mn.gov"
WFSERVLET = f"{BASE}/ibi_apps/WFServlet.ibfs"
OUT_DIR = Path("data/raw/mn/mde_analytics")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}

# TOPICIDs that use the "List files" interface. Names become output subfolders.
FILE_TOPICS = [
    {"id": 1,   "name": "assessment"},
    {"id": 450, "name": "north_star"},
    {"id": 545, "name": "graduation"},
    {"id": 588, "name": "course_taking"},
    {"id": 486, "name": "counting_all_students"},
    {"id": 516, "name": "american_indian_achievement"},
    {"id": 4,   "name": "schools_and_districts"},
    {"id": 2,   "name": "student"},
    {"id": 133, "name": "discipline"},
    {"id": 87,  "name": "act"},
    {"id": 455, "name": "child_count"},
    {"id": 242, "name": "student_survey_reports"},
    {"id": 11,  "name": "student_survey_tables"},
]
TOPIC_FILTER = {int(x) for x in os.environ.get("MN_TOPICS", "").replace(" ", "").split(",") if x}

MANIFEST_FIELDS = ["state", "topic", "label", "meta", "fmt", "file_url",
                   "local_path", "status", "size_bytes", "sha256"]


def make_session():
    s = requests.Session()
    retry = Retry(total=2, connect=2, read=2, backoff_factor=0.5,
                  status_forcelist=[429, 500, 502, 503, 504], raise_on_status=False)
    ad = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s.mount("https://", ad)
    s.mount("http://", ad)
    s.headers.update(HEADERS)
    return s


def _list_files(session, topic_id):
    """Replicate the topic's 'List files' POST and parse the resulting table.

    Returns [{meta: [...], label, fmt, url}]. ALL filter values (FOC_NONE) are
    submitted so every available file is listed in one request.
    """
    launch = f"{BASE}/MDEAnalytics/DataTopic.jsp?TOPICID={topic_id}"
    session.get(launch, timeout=60)  # establish session/cookies
    driver = (f"{BASE}/ibi_apps/WFServlet?IBIF_ex=mdea_ddl_driver"
              f"&TOPICID={topic_id}&DDL_VARS=5")
    dr = session.get(driver, timeout=60, headers={"Referer": launch})

    # The listing form carries a per-session WebFOCUS auth token; scrape it from
    # the driver page rather than hardcoding.
    soup_dr = BeautifulSoup(dr.text, "html.parser")
    payload = {}
    for inp in soup_dr.select("input[type=hidden][name]"):
        payload[inp["name"]] = inp.get("value", "")
    payload.update({
        "IBIAPP_app": "mdea_reports",
        "IBIF_ex": "mdea_ddl_file_listing",   # the file-listing procedure
        "TOPICID": str(topic_id),
        "IBIMR_sub_action": "MR_USER_FEX",
    })
    # FOC_NONE = "ALL" for each filter dropdown
    for i in range(1, 6):
        payload[f"COMBO{i}"] = "FOC_NONE"

    r = session.post(WFSERVLET, data=payload, timeout=120,
                     headers={"Referer": driver})
    if r.status_code >= 400 or "GET_FILE" not in r.text:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for tr in soup.select("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.select("td,th")]
        for a in tr.select("a[href]"):
            href = a.get("href", "")
            if "GET_FILE" not in href:
                continue
            out.append({"meta": [c for c in cells[:6] if c],
                        "label": cells[5] if len(cells) > 5 else " ".join(cells[:3]),
                        "fmt": a.get_text(strip=True), "url": href})
    return out


def _filename(resp, item, topic):
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", cd)
    if m:
        return safe_filename(unquote(m.group(1)).strip())
    base = "_".join(x for x in item["meta"] if x)[:80] or item["label"][:60] or "file"
    return safe_filename(f"{base}.{item['fmt'] or 'dat'}")


def _download(session, item, topic):
    row = {"state": "MN", "topic": topic, "label": item["label"][:150],
           "meta": " | ".join(item["meta"]), "fmt": item["fmt"], "file_url": item["url"],
           "local_path": "", "status": "", "size_bytes": "", "sha256": ""}
    try:
        resp = session.get(item["url"], timeout=300, stream=True)
        if resp.status_code >= 400:
            row["status"] = f"http_{resp.status_code}"
            return row
        fname = _filename(resp, item, topic)
        dest = OUT_DIR / topic / fname
        dest.parent.mkdir(parents=True, exist_ok=True)
        row["local_path"] = str(dest)
        if dest.exists() and dest.stat().st_size > 0:
            resp.close()
            row.update(status="skipped_existing", size_bytes=dest.stat().st_size,
                       sha256=sha256_file(dest))
            return row
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=4 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    except Exception as e:
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
    session = make_session()
    topics = [t for t in FILE_TOPICS if not TOPIC_FILTER or t["id"] in TOPIC_FILTER]

    all_items = []
    for t in topics:
        try:
            items = _list_files(session, t["id"])
        except Exception as e:
            print(f"  topic {t['id']} {t['name']}: error {str(e)[:70]}")
            continue
        # de-dupe by url within a topic
        seen, uniq = set(), []
        for it in items:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            it["topic"] = t["name"]
            uniq.append(it)
        print(f"  topic {t['id']:>3} {t['name']:28s}: {len(uniq)} files")
        all_items.extend(uniq)
        time.sleep(1)

    print(f"\nTotal files to fetch: {len(all_items)}")
    manifest = []
    for it in tqdm.tqdm(all_items, desc="MN MDE Analytics"):
        manifest.append(_download(session, it, it["topic"]))
        time.sleep(0.15)

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    mb = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit()) / 1e6
    print(f"\nDone. {ok}/{len(manifest)} files ({mb:.1f} MB). Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
