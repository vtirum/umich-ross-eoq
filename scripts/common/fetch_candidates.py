"""
common/fetch_candidates.py — download the new files found by site_audit.py

site_audit.py reports candidates without fetching them. This downloads them, by
default only real tabular formats (.xlsx/.xls/.csv/.zip) — a DOE site sweep picks up
hundreds of PDF guidance documents that are not data.

Files land in <out-dir>/<category>/ and a manifest is written alongside, matching the
layout of the state scrapers so verify_dims.py can run over the result.

Run:
    python scripts/common/fetch_candidates.py data/raw/in/audit_candidates.csv \\
        --out data/raw/in/audit_new
    # include PDFs too:
    python scripts/common/fetch_candidates.py <csv> --out <dir> --formats xlsx,xls,csv,zip,pdf
"""

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from common.file_utils import safe_filename, sha256_file
from common.manifest import write_csv

HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")}
MANIFEST_FIELDS = ["state", "category", "dims", "label", "file_url", "local_path",
                   "status", "size_bytes", "sha256"]


def make_session():
    s = requests.Session()
    retry = Retry(total=2, connect=2, read=2, backoff_factor=0.5,
                  status_forcelist=[429, 500, 502, 503, 504], raise_on_status=False)
    ad = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s.mount("https://", ad)
    s.mount("http://", ad)
    s.headers.update(HEADERS)
    return s


def _filename(resp, url, label):
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", cd)
    if m:
        return safe_filename(unquote(m.group(1)).strip())
    name = unquote(Path(urlparse(url).path).name)
    return safe_filename(name or (label[:60] + ".xlsx"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("--out", required=True)
    ap.add_argument("--formats", default="xlsx,xls,csv,zip")
    args = ap.parse_args()

    exts = tuple("." + e.strip().lstrip(".").lower() for e in args.formats.split(","))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(open(args.candidates, encoding="utf-8")))
    todo = [r for r in rows if urlparse(r["url"]).path.lower().endswith(exts)]
    print(f"{len(rows)} candidates -> {len(todo)} matching {args.formats}")

    session = make_session()
    manifest = []
    for r in tqdm.tqdm(todo, desc="fetching"):
        cat = r.get("category") or "other"
        row = {"state": r.get("state", ""), "category": cat, "dims": r.get("dims", ""),
               "label": r.get("label", "")[:150], "file_url": r["url"],
               "local_path": "", "status": "", "size_bytes": "", "sha256": ""}
        try:
            resp = session.get(r["url"], timeout=180, stream=True)
            if resp.status_code >= 400:
                row["status"] = f"http_{resp.status_code}"
                manifest.append(row)
                continue
            dest = out_dir / cat / _filename(resp, r["url"], row["label"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            row["local_path"] = str(dest)
            if dest.exists() and dest.stat().st_size > 0:
                resp.close()
                row.update(status="skipped_existing", size_bytes=dest.stat().st_size,
                           sha256=sha256_file(dest))
                manifest.append(row)
                continue
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        except Exception as e:
            row["status"] = f"error:{str(e)[:60]}"
            manifest.append(row)
            continue
        if dest.stat().st_size < 50:
            dest.unlink()
            row["status"] = "too_small"
        else:
            row.update(status="downloaded", size_bytes=dest.stat().st_size,
                       sha256=sha256_file(dest))
        manifest.append(row)
        time.sleep(0.1)

    mpath = out_dir / "manifest.csv"
    write_csv(mpath, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    mb = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit()) / 1e6
    print(f"\nDone. {ok}/{len(manifest)} files ({mb:.1f} MB). Manifest: {mpath}")


if __name__ == "__main__":
    main()
