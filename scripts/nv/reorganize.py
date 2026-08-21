"""
Reorganise data/raw/nv into the layout the other states use.

Nevada grew by accretion across several scripts and ended up awkward:

  - 9,061 report-card dashboard files, each a JSON list holding exactly ONE record
    with an identical 67-key schema. Unusable for analysis without writing a loader.
  - 12 assessment directories holding exactly one file each, all named
    `all_years.csv`, so the exam is encoded only in the directory name.
  - three empty directories left by exams that returned nothing (ACT has no
    subgroup breakdown; CTE moved to doe/).
  - four separate manifests and a stray .DS_Store.

This consolidates the dashboard into one table, flattens the assessment files,
merges the manifests and clears the empties. Raw JSON is kept - the CSV is added
alongside, nothing is deleted except empty directories and .DS_Store.

Left alone deliberately:
  reportcard/detail/  rows are headerless `cells` arrays and the column names are
                      not in the payload or the manifest, so converting them to CSV
                      would produce meaningless column names. Kept as JSON.
  *_crdc/, finance_f33/  federal supplements, laid out identically in all 17 states.
                      Moving them here only would break cross-state consistency.

Idempotent - safe to re-run.

    python scripts/nv/reorganize.py [--dry-run]
"""

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm

from common.manifest import write_csv

NV = Path("data/raw/nv")
RC = NV / "reportcard"

# assessment directory -> flattened filename
ASSESSMENT_DIRS = {
    "assessment_sbac": "sbac",
    "assessment_sbac_subgroups": "sbac_subgroups",
    "assessment_ccr_grade11": "ccr_grade11",
    "assessment_ccr_grade11_subgroups": "ccr_grade11_subgroups",
    "assessment_science_5_8": "science_5_8",
    "assessment_science_5_8_subgroups": "science_5_8_subgroups",
    "assessment_science_9_10": "science_9_10",
    "assessment_science_9_10_subgroups": "science_9_10_subgroups",
    "assessment_naa": "naa",
    "assessment_naa_subgroups": "naa_subgroups",
    "assessment_elpa": "elpa",
    "assessment_elpa_subgroups": "elpa_subgroups",
}


def consolidate_dashboard(dry_run=False):
    """9,061 one-record JSON files -> one CSV."""
    files = sorted(RC.glob("dashboard/*/*/*.json"))
    if not files:
        print("  dashboard: no files")
        return 0
    dest = RC / "dashboard.csv"
    rows, keys = [], []
    for f in tqdm.tqdm(files, desc="  reading dashboard", leave=False):
        try:
            payload = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for rec in (payload if isinstance(payload, list) else [payload]):
            if not isinstance(rec, dict):
                continue
            # level and year come from the path; orgId is already in the record
            rec = {"level": f.parts[-3], "year_dir": f.stem, **rec}
            rows.append(rec)
            if not keys:
                keys = list(rec.keys())
    if not rows:
        print("  dashboard: nothing parsed")
        return 0
    # union of keys, stable order
    allkeys = list(keys)
    for r in rows:
        for k in r:
            if k not in allkeys:
                allkeys.append(k)
    print(f"  dashboard: {len(files):,} files -> {len(rows):,} rows x {len(allkeys)} cols")
    if not dry_run:
        with open(dest, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=allkeys, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"    wrote {dest} ({dest.stat().st_size/1e6:.1f} MB)")
    return len(rows)


def flatten_assessment(dry_run=False):
    """12 single-file directories -> assessment/<exam>.csv."""
    out = NV / "assessment"
    moved = 0
    for dirname, slug in ASSESSMENT_DIRS.items():
        src_dir = NV / dirname
        if not src_dir.is_dir():
            continue
        src = src_dir / "all_years.csv"
        if not src.exists():
            continue
        dest = out / f"{slug}.csv"
        print(f"  {dirname}/all_years.csv -> assessment/{slug}.csv")
        if not dry_run:
            out.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            if not any(src_dir.iterdir()):
                src_dir.rmdir()
        moved += 1
    return moved


def merge_manifests(dry_run=False):
    """Fold the per-script manifests into one, keeping their own columns."""
    sources = [
        (NV / "manifest.csv", "assessment"),
        (NV / "subgroups_manifest.csv", "assessment_subgroups"),
        (RC / "dashboard_manifest.csv", "reportcard_dashboard"),
        (RC / "detail_manifest.csv", "reportcard_detail"),
        (NV / "doe" / "doe_manifest.csv", "doe"),
    ]
    rows, fields = [], ["source"]
    for path, label in sources:
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for rec in csv.DictReader(fh):
                rec = {"source": label, **rec}
                for k in rec:
                    if k not in fields:
                        fields.append(k)
                rows.append(rec)
    print(f"  manifests: {len(rows):,} rows from {len([p for p,_ in sources if p.exists()])} files")
    if rows and not dry_run:
        # the flattened assessment files moved, so repoint those paths
        for r in rows:
            lp = r.get("local_path", "")
            for dirname, slug in ASSESSMENT_DIRS.items():
                if f"/{dirname}/all_years.csv" in lp:
                    r["local_path"] = f"data/raw/nv/assessment/{slug}.csv"
        write_csv(NV / "manifest_all.csv", rows, fields)
        print(f"    wrote {NV / 'manifest_all.csv'}")
    return len(rows)


def clean_empties(dry_run=False):
    removed = []
    for p in sorted(NV.rglob("*")):
        if p.is_dir() and not any(p.iterdir()):
            removed.append(p)
            if not dry_run:
                p.rmdir()
    for junk in NV.rglob(".DS_Store"):
        removed.append(junk)
        if not dry_run:
            junk.unlink()
    for p in removed:
        print(f"  removed {p.relative_to(NV)}")
    return len(removed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not NV.is_dir():
        print(f"{NV} not found")
        return
    before = sum(1 for p in NV.rglob("*") if p.is_file())
    print(f"data/raw/nv: {before:,} files before\n")

    print("1. consolidating report-card dashboard")
    consolidate_dashboard(args.dry_run)
    print("\n2. flattening assessment directories")
    flatten_assessment(args.dry_run)
    print("\n3. merging manifests")
    merge_manifests(args.dry_run)
    print("\n4. clearing empty directories and junk")
    clean_empties(args.dry_run)

    after = sum(1 for p in NV.rglob("*") if p.is_file())
    print(f"\n{'(dry run) ' if args.dry_run else ''}{before:,} -> {after:,} files")


if __name__ == "__main__":
    main()
