"""
Crawl-and-download engine for states that publish plain files on a few pages.

Used by NM, ID and MS, which differ only in their seed URLs. A state supplies
seeds plus a regex for which page links to follow, and run() handles the crawl,
categorisation, skip-existing downloads and manifest.

Note: some hosts (mdek12.org/sites/default/files) return 403 unless the request
carries a same-site Referer, so download() retries once with one.
"""

import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import tqdm
import requests
from bs4 import BeautifulSoup

from common.http_client import BROWSER_UA, make_session
from common.file_utils import safe_filename, sha256_file
from common.manifest import write_csv

FILE_EXTS = (".xlsx", ".xls", ".csv", ".zip", ".txt", ".tab", ".accdb", ".mdb", ".pdf")
HEADERS = {"User-Agent": BROWSER_UA}
SKIP = re.compile(r"(mailto:|tel:|javascript:|\.jpg|\.png|\.gif|\.svg|facebook|twitter|"
                  r"youtube|linkedin|instagram)", re.I)

MANIFEST_FIELDS = ["state", "category", "label", "file_url", "local_path",
                   "status", "size_bytes", "sha256"]

CATEGORY_KEYWORDS = {
    "assessment": ["assess", "proficien", "isat", "iri", "naep", "sat", "act ", "map ",
                   "istation", "caaspp", "eoc", "test", "score", "ela", "math", "science",
                   "language arts", "reading", "wida", "access", "elpa", "questar"],
    "enrollment": ["enroll", "membership", "demograph", "student count", "headcount",
                   "free and reduced", "frl", "poverty", "ell", "english learner",
                   "special education", "child count", "mobility"],
    "attendance": ["attendance", "absentee", "chronic", "ada", "adm", "truan"],
    "graduation": ["graduat", "dropout", "cohort", "completion", "college go", "diploma"],
    "discipline": ["disciplin", "suspen", "expul", "incident", "crime", "safety", "bully"],
    "staff":      ["staff", "teacher", "personnel", "educator", "salary", "certif",
                   "faculty", "administrator", "superintendent", "principal"],
    "finance":    ["financ", "expenditure", "revenue", "budget", "per pupil", "levy",
                   "fund", "fiscal", "salaries", "transparency", "support unit"],
    "directory":  ["directory", "listing", "school list", "district list", "contact",
                   "org", "address"],
}


def categorise(label, url):
    hay = f"{label} {unquote(url)}".lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(k in hay for k in kws):
            return cat
    return "other"


def crawl(session, seeds, follow_re, depth=1, verbose=True):
    """Return {file_url: label} found across seeds and followed pages."""
    files, visited = {}, set()
    frontier = [(u, 0) for u in seeds]
    while frontier:
        url, d = frontier.pop(0)
        base = url.split("#")[0]
        if base in visited or d > depth:
            continue
        visited.add(base)
        try:
            r = session.get(base, timeout=45)
            if r.status_code >= 400 or "html" not in r.headers.get("Content-Type", ""):
                continue
        except Exception as e:
            if verbose:
                print(f"  ! {base[:70]}: {str(e)[:50]}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        n_before = len(files)
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href or SKIP.search(href):
                continue
            full = urljoin(base, href).split("#")[0]
            label = a.get_text(" ", strip=True)
            if urlparse(full).path.lower().endswith(FILE_EXTS):
                if full not in files or (label and not files.get(full)):
                    files[full] = label or Path(urlparse(full).path).stem
            elif d < depth and follow_re and follow_re.search(full):
                if full not in visited:
                    frontier.append((full, d + 1))
        if verbose:
            print(f"  [d{d}] {base[:66]} (+{len(files)-n_before} files, {len(files)} total)")
        time.sleep(0.2)
    return files


# a URL path whose last segment is one of these tells us nothing about the file -
# every link on the page ends the same way, so naming by basename collides silently
GENERIC_NAMES = re.compile(r"^(getdocumentfile|download|file|document|export|view|"
                           r"attachment|index|default)?(\.[a-z0-9]+)?$", re.I)


def choose_dest(url, label, cat_dir, claimed):
    """Destination path for `url`, never one another URL has already taken.

    Two failure modes this avoids. Handler-style URLs (`.../GetDocumentFile?id=123`)
    all share a basename, so naming by basename makes every download overwrite the
    last - Arizona lost 69 files that way, each recorded in the manifest as a success.
    And distinct files in different site folders can legitimately share a basename.
    """
    base = safe_filename(unquote(Path(urlparse(url).path).name))
    if GENERIC_NAMES.match(base):
        # fall back to the link text, keeping whatever extension the URL implied
        ext = Path(base).suffix or Path(unquote(url)).suffix
        if len(ext) > 6 or "/" in ext:
            ext = ""
        base = safe_filename((label or "file")[:120] + ext)
    dest = cat_dir / base
    if claimed.get(str(dest), url) == url:
        claimed[str(dest)] = url
        return dest
    stem, suffix = Path(base).stem, Path(base).suffix
    for n in range(2, 500):
        cand = cat_dir / f"{stem}__{n}{suffix}"
        if claimed.get(str(cand), url) == url:
            claimed[str(cand)] = url
            return cand
    raise RuntimeError(f"cannot find a free name for {url}")


def looks_like_html(path):
    """True if the bytes are a web page - an error/login page saved under a data name."""
    head = open(path, "rb").read(600).lstrip()[:400].lower()
    return head.startswith((b"<!doctype html", b"<html", b"<head")) or b"<html" in head[:200]


def download(session, url, label, out_dir, state, claimed=None, flat=False):
    cat = categorise(label, url)
    # `flat` keeps everything in one directory - used where a state's files already
    # live flat on disk and re-filing them would strand the existing catalogue
    cat_dir = Path(out_dir) if flat else Path(out_dir) / cat
    cat_dir.mkdir(parents=True, exist_ok=True)
    dest = choose_dest(url, label, cat_dir, claimed if claimed is not None else {})
    row = {"state": state, "category": cat, "label": label[:150], "file_url": url,
           "local_path": str(dest), "status": "", "size_bytes": "", "sha256": ""}
    if dest.exists() and dest.stat().st_size > 0:
        row.update(status="skipped_existing", size_bytes=dest.stat().st_size,
                   sha256=sha256_file(dest))
        return row
    try:
        resp = session.get(url, timeout=180, stream=True)
        if resp.status_code == 403:
            # some hosts (e.g. mdek12.org/sites/default/files) reject requests that
            # arrive without a same-site Referer
            origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}/"
            resp = session.get(url, timeout=180, stream=True, headers={"Referer": origin})
        if resp.status_code >= 400:
            row["status"] = f"http_{resp.status_code}"
            return row
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        if dest.exists():
            dest.unlink()
        row["status"] = f"error:{str(e)[:60]}"
        return row
    if dest.stat().st_size < 1024:
        dest.unlink()
        row["status"] = "too_small"
        return row
    if not url.lower().rstrip("/").endswith((".html", ".htm")) and looks_like_html(dest):
        # an error, login or Cloudflare page served with a 200 and a data filename
        dest.unlink()
        row["status"] = "html_not_data"
        return row
    row.update(status="downloaded", size_bytes=dest.stat().st_size, sha256=sha256_file(dest))
    return row


def run(state, seeds, out_dir, follow=None, depth=1, extra_files=None, flat=False):
    """Crawl + download + manifest. `extra_files` is an optional {url: label} to add."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = make_session()

    print(f"Crawling {state} from {len(seeds)} seed(s), depth={depth}")
    follow_re = re.compile(follow, re.I) if follow else None
    files = crawl(session, seeds, follow_re, depth=depth)
    if extra_files:
        files.update(extra_files)
    print(f"\n{len(files)} unique files")

    from collections import Counter
    print("by category:", dict(Counter(categorise(l, u) for u, l in files.items()).most_common()))

    manifest, claimed = [], {}
    for url, label in tqdm.tqdm(files.items(), desc=f"{state} downloads"):
        manifest.append(download(session, url, label, out_dir, state, claimed, flat))
        time.sleep(0.1)

    mpath = out_dir / "manifest.csv"
    write_csv(mpath, manifest, MANIFEST_FIELDS)
    ok = sum(1 for r in manifest if r["status"] in ("downloaded", "skipped_existing"))
    mb = sum(int(r["size_bytes"]) for r in manifest if str(r["size_bytes"]).isdigit()) / 1e6
    print(f"\nDone. {ok}/{len(manifest)} files ({mb:.1f} MB). Manifest: {mpath}")
    return manifest
