"""
common/verify_dims.py — verify demographic breakdowns by reading the files themselves

The LLM labeller (common/llm_assist.py) guesses demographic dimensions from a file's
TITLE. That is useful for triage but it over-claims: Missouri's "APR Summary by
Districts" was tagged race|gender|iep_504|ell|frl and actually contains only
accountability points. Titles are not evidence.

For files already on disk we can do better than guessing — open them and look. This
reads each spreadsheet/CSV's header row plus a sample of values and reports which
demographic dimensions are ACTUALLY present:

    race     Hispanic/Black/White/Asian/American Indian/Two or More/ethnicity
    gender   Male/Female/sex
    iep_504  IEP/504/special education/students with disabilities
    ell      EL/ELL/LEP/English learner
    frl      free/reduced-price meals/lunch, economically disadvantaged

Detection covers both layouts state agencies use: wide (one column per subgroup)
and long (a "Student Group"/"Category" column whose VALUES are the subgroups).

Writes `<manifest>_verified.csv` with columns:
    verified_dims   dimensions found in the file (pipe-separated)
    dims_source     header | values | both | none | unreadable

Run:
    python scripts/common/verify_dims.py data/raw/mo/mcds/manifest_llm.csv
    python scripts/common/verify_dims.py data/raw/in/manifest_llm.csv --limit 200
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
                header, values = _read_xlsx(p)   # often xlsx mislabelled
            except (zipfile.BadZipFile, KeyError):
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
