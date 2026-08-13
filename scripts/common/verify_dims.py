"""
Detect demographic breakdowns by reading the files themselves.

llm_assist guesses dimensions from a file's title, which over- and (more often)
under-claims: measured against contents it missed 154 Indiana and 43 Missouri
files that genuinely carry breakdowns. This opens each file instead and looks for
race, gender, iep_504, ell and frl in the header row and a sample of values,
covering both layouts states use (one column per subgroup, or a "Student Group"
column whose values are the subgroups).

Writes <manifest>_verified.csv with verified_dims and dims_source (header /
values / both / none / unreadable / skipped_format).

Legacy .xls needs xlrd; openpyxl cannot read it, and before that fallback existed
46 New Mexico files were reported as unreadable.

    python scripts/common/verify_dims.py data/raw/mo/mcds/manifest_llm.csv
"""

import argparse
import csv
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PATTERNS = {
    "race": re.compile(r"\b(hispanic|latino|black|african.?american|white|asian|"
                       r"american.indian|alaska|pacific.islander|native.hawaiian|"
                       r"two.or.more|multi.?racial|race|ethnic)", re.I),
    "gender": re.compile(r"\b(male|female|gender|\bsex\b)", re.I),
    "iep_504": re.compile(r"(\biep\b|\b504\b|special.ed|students.with.disab|"
                          r"disabilit|sped\b)", re.I),
    "ell": re.compile(r"(\bell\b|\bel\b|\blep\b|english.learner|english.language.learner|"
                      r"limited.english)", re.I),
    "frl": re.compile(r"(free.and.reduced|free/reduced|free.or.reduced|frl\b|frpl\b|"
                      r"econom\w* disadvantaged|\bfarms\b|reduced.price)", re.I),
}
# words that make a bare "EL"/"male" match a false positive
NEGATIVE = re.compile(r"(female_?head|element|develop|male.?factor)", re.I)

MAX_ROWS = 400          # sample depth for value-based detection
MAX_BYTES = 300_000_000  # skip files too large to open quickly


def _scan_text(cells):
    """Return set of dims matched across an iterable of strings."""
    found = set()
    for c in cells:
        if not c:
            continue
        s = str(c)
        if NEGATIVE.search(s):
            continue
        for dim, pat in PATTERNS.items():
            if dim not in found and pat.search(s):
                found.add(dim)
    return found


def _read_xlsx(path):
    import openpyxl
    header, values = [], []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets[:4]:
            for i, row in enumerate(ws.iter_rows(max_row=MAX_ROWS, values_only=True)):
                if row is None:
                    continue
                cells = [c for c in row if c is not None]
                if i < 6 and len(cells) > 2 and not header:
                    header = [str(c) for c in cells]
                values.extend(str(c) for c in cells[:40])
                if i > MAX_ROWS:
                    break
    finally:
        wb.close()
    return header, values


def _read_xls_legacy(path):
    """Read a legacy BIFF .xls via xlrd (openpyxl only handles OOXML)."""
    import xlrd
    header, values = [], []
    bk = xlrd.open_workbook(path, on_demand=True)
    try:
        for sn in bk.sheet_names()[:4]:
            sh = bk.sheet_by_name(sn)
            for i in range(min(sh.nrows, MAX_ROWS)):
                cells = [str(c) for c in sh.row_values(i) if str(c).strip()]
                if i < 6 and len(cells) > 2 and not header:
                    header = cells
                values.extend(cells[:40])
                if len(values) > MAX_ROWS * 4:
                    break
    finally:
        bk.release_resources()
    return header, values


def _read_csvlike(path, delim=None):
    header, values = [], []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        sample = f.read(65536)
        f.seek(0)
        if delim is None:
            delim = "\t" if sample.count("\t") > sample.count(",") else ","
        for i, row in enumerate(csv.reader(f, delimiter=delim)):
            if i == 0:
                header = row
            values.extend(row[:40])
            if i > MAX_ROWS:
                break
    return header, values


def inspect(path):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return set(), "missing"
    if p.stat().st_size > MAX_BYTES:
        return set(), "too_large"
    suf = p.suffix.lower()
    try:
        if suf in (".xlsx", ".xlsm"):
            header, values = _read_xlsx(p)
        elif suf in (".csv", ".txt", ".tab"):
            header, values = _read_csvlike(p)
        elif suf == ".xls":
            try:
                header, values = _read_xlsx(p)   # sometimes an xlsx mislabelled .xls
            except (zipfile.BadZipFile, KeyError, Exception):
                # genuine legacy BIFF — openpyxl cannot read it (46 NM files landed
                # here as "unreadable" before this fallback existed)
                try:
                    header, values = _read_xls_legacy(p)
                except Exception:
                    return set(), "unreadable"
        else:
            return set(), "skipped_format"
    except Exception:
        return set(), "unreadable"

    from_header = _scan_text(header)
    from_values = _scan_text(values)
    dims = from_header | from_values
    if not dims:
        src = "none"
    elif from_header and from_values:
        src = "both"
    elif from_header:
        src = "header"
    else:
        src = "values"
    return dims, src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    src = Path(args.manifest)
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    if args.limit:
        rows = rows[:args.limit]
    path_key = next((k for k in ("local_path", "path") if k in rows[0]), None)

    agree = over = under = 0
    for i, r in enumerate(rows, 1):
        dims, srcinfo = inspect(r.get(path_key, ""))
        r["verified_dims"] = "|".join(sorted(dims))
        r["dims_source"] = srcinfo
        claimed = set(filter(None, (r.get("llm_dims") or "").split("|")))
        if srcinfo in ("missing", "too_large", "unreadable", "skipped_format"):
            pass
        elif claimed and not dims:
            over += 1
        elif dims and not claimed:
            under += 1
        elif claimed or dims:
            agree += 1
        if i % 50 == 0:
            print(f"  inspected {i}/{len(rows)}")

    dest = src.with_name(src.stem.replace("_llm", "") + "_verified.csv")
    with open(dest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    have = [r for r in rows if r["verified_dims"]]
    print(f"\nwrote {dest}")
    print(f"files with VERIFIED demographic data: {len(have)}/{len(rows)}")
    print("verified dimensions:",
          dict(Counter(d for r in have for d in r["verified_dims"].split("|")).most_common()))
    print("readability:", dict(Counter(r["dims_source"] for r in rows).most_common()))
    if "llm_dims" in rows[0]:
        print(f"\nLLM title-guess vs file contents: agree={agree} over-claimed={over} missed={under}")


if __name__ == "__main__":
    main()
