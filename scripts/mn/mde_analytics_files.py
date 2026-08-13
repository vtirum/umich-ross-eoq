"""
Minnesota MDE Analytics bulk files (pub.education.mn.gov/MDEAnalytics).

The Data Reports and Analytics portal has 59 topics at DataTopic.jsp?TOPICID=N.
Most are report runners behind PerimeterX, but the ones that matter are file
listers: choose test/year/subject/grade, press "List files", and get direct
download links. That distinction is the whole trick - the portal looks like a
dashboard and behaves like a static file index.

Assessment files span 1998-2025 (MCA, MTAS, Alt-MCA, MOD, GRAD, BST, ACCESS,
TEAE, MTELL, SOLOM, WIDA), each with State/County/District/School sheets and
Group Category + Student Group columns covering race, gender, special education,
English proficiency, economic status, homeless, migrant, military and SLIFE.

Blocked: the report-runner topics (discipline, UFARS finance) trigger a
PerimeterX challenge on "Run Report" and never generate. Use CRDC and Census F-33
for those.

Output:   data/raw/mn/mde_analytics/<topic>/<filename>
Env:      MN_TOPICS=1,545,87,2,4,450,588
"""

import sys
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
from bs4 import BeautifulSoup

from common.http_client import BROWSER_UA, make_session
from common.file_utils import safe_filename, sha256_file
from common.manifest import write_csv

BASE = "https://pub.education.mn.gov"
WFSERVLET = f"{BASE}/ibi_apps/WFServlet.ibfs"
OUT_DIR = Path("data/raw/mn/mde_analytics")
MANIFEST_PATH = OUT_DIR / "manifest.csv"

HEADERS = {"User-Agent": BROWSER_UA}

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
