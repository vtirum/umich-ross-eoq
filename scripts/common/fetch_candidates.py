"""
Download the new files reported by site_audit.py.

Defaults to tabular formats only. A DOE sweep turns up far more PDF guidance than
data (Indiana's was 683 PDFs against 97 data files), so pass --formats explicitly
if you want those too.

    python scripts/common/fetch_candidates.py data/raw/in/audit_candidates.csv \
        --out data/raw/in/audit_new
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

from common.http_client import BROWSER_UA, make_session
from common.file_utils import safe_filename, sha256_file
from common.manifest import write_csv

HEADERS = {"User-Agent": BROWSER_UA}
MANIFEST_FIELDS = ["state", "category", "dims", "label", "file_url", "local_path",
                   "status", "size_bytes", "sha256"]


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
