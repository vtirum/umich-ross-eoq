"""
Sweep a state DOE site for bulk data files we never collected.

Crawls seed pages, extracts every file link, diffs against an existing manifest
and reports only what is new. Nothing is downloaded here; feed the output to
fetch_candidates.py.

Page links are filtered by keyword first. Pass --no-rank on link-heavy sites:
LLM-ranking every link on an archive page costs far more than it adds.

    python scripts/common/site_audit.py --state in --no-rank --depth 2 \
        --seeds <urls...> --manifest data/raw/in/manifest.csv \
        --out data/raw/in/audit_candidates.csv
"""

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from bs4 import BeautifulSoup

from common import llm_assist as L

FILE_EXTS = (".xlsx", ".xls", ".csv", ".zip", ".txt", ".tab", ".pdf", ".accdb", ".mdb")
HANDLER_HINTS = ("filedownloadwebhandler", "get_file", "getfile", "download.aspx",
                 "idcservice=get_file", "servlet")
HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")}
SKIP_LINK = re.compile(r"(mailto:|tel:|javascript:|\.jpg|\.png|\.gif|\.svg|#$"
                       r"|facebook|twitter|youtube|linkedin|instagram)", re.I)


def is_file(url):
    p = urlparse(url).path.lower()
    if p.endswith(FILE_EXTS):
        return True
    return any(h in url.lower() for h in HANDLER_HINTS)


CRAWL_HINT = re.compile(r"(data|report|statistic|download|file|assess|enroll|"
                        r"financ|staff|teacher|graduat|attend|disciplin|archive|"
                        r"result|accountab|demograph)", re.I)


def crawl(seeds, host_filter, depth, session, verbose=True, use_llm_rank=True):
    """Returns (files: {url: label}, visited: set)."""
    files, visited = {}, set()
    frontier = [(s, 0) for s in seeds]
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
                print(f"    ! {base[:70]}: {str(e)[:50]}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        page_links = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href or SKIP_LINK.search(href):
                continue
            full = urljoin(base, href).split("#")[0]
            label = a.get_text(" ", strip=True)
            if is_file(full):
                files.setdefault(full, label or Path(urlparse(full).path).stem)
            elif host_filter in urlparse(full).netloc and full not in visited:
                page_links.append({"text": label, "url": full})
        if verbose:
            print(f"  [d{d}] {base[:68]} -> {len(files)} files so far, {len(page_links)} links")
        # prioritise which pages to follow next
        if d < depth and page_links:
            uniq, seen = [], set()
            for l in page_links:
                if l["url"] in seen:
                    continue
                seen.add(l["url"])
                uniq.append(l)
            # Keyword prefilter first — LLM-ranking every link on a link-heavy
            # archive page costs far more than it adds.
            cand = [l for l in uniq if CRAWL_HINT.search(l["text"] + " " + l["url"])]
            if use_llm_rank and L.available() and len(cand) <= 60:
                scores = L.rank_pages(cand)
                cand = [l for l, sc in zip(cand, scores) if sc >= 2]
            for l in cand:
                frontier.append((l["url"], d + 1))
        time.sleep(0.2)
    return files, visited


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--seeds", nargs="+", required=True)
    ap.add_argument("--manifest", action="append", default=[],
                    help="existing manifest(s) to diff against; repeatable")
    ap.add_argument("--out", required=True)
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--no-rank", action="store_true",
                    help="skip LLM page-ranking (keyword prefilter only) — much faster")
    args = ap.parse_args()

    session = requests.Session()
    session.headers.update(HEADERS)
    host = urlparse(args.seeds[0]).netloc

    print(f"Crawling {args.state.upper()} from {len(args.seeds)} seed(s), depth={args.depth}")
    files, visited = crawl(args.seeds, host, args.depth, session,
                           use_llm_rank=not args.no_rank)
    print(f"\nvisited {len(visited)} pages, found {len(files)} file links")

    # diff against what we already downloaded
    known = set()
    for mp in args.manifest:
        p = Path(mp)
        if not p.exists():
            continue
        for row in csv.DictReader(open(p, encoding="utf-8")):
            for k in ("file_url", "url", "wayback_url"):
                if row.get(k):
                    known.add(row[k].split("#")[0])
                    known.add(Path(urlparse(row[k]).path).name.lower())
    new = {u: lb for u, lb in files.items()
           if u not in known and Path(urlparse(u).path).name.lower() not in known}
    print(f"already in manifest: {len(files)-len(new)} | NEW candidates: {len(new)}")

    items = [{"label": lb, "url": u} for u, lb in new.items()]
    res = L.classify_files(items, verbose=True) if (items and L.available()) else [None] * len(items)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["state", "category", "dims", "year", "label", "url"])
        for it, c in zip(items, res):
            w.writerow([args.state.upper(), (c or {}).get("category", ""),
                        "|".join((c or {}).get("dims", [])), (c or {}).get("year", "") or "",
                        it["label"][:150], it["url"]])

    from collections import Counter
    print(f"\nwrote {args.out}")
    print("new by category:", dict(Counter((c or {}).get("category", "?") for c in res).most_common()))
    demog = [(it, c) for it, c in zip(items, res) if c and c["dims"]]
    print(f"new files with demographic breakdowns: {len(demog)}")
    for it, c in demog[:15]:
        print(f"   [{c['category']:11s}] {'|'.join(c['dims']):22s} {it['label'][:60]}")


if __name__ == "__main__":
    main()
