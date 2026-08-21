"""
Rebuild data/raw/az/reportcards/manifest.csv from the files on disk.

Needed once, because IncrementalManifest used to truncate the manifest on every run:
a run scoped to one fiscal year left a manifest describing only that year, even though
eight years of JSON sat on disk. The class now carries prior rows forward
(common/manifest.py), but the manifest written before that fix is still short, and the
only way to recover the missing years without re-downloading ~11 GB is to read the tree.

Entity names come from each year's entities/entity_list.json. `status_code` is recorded
as 200 for files that exist - the download only writes a file when the request
succeeded - and `url` is left blank rather than reconstructed, since a guessed URL in a
provenance record is worse than an empty one.

    python scripts/az/rebuild_reportcards_manifest.py [--dry-run]
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm

OUT_DIR = Path("data/raw/az/reportcards")
FIELDS = ["fiscal_year", "entity_id", "entity_name", "entity_kind",
          "report", "url", "status_code", "saved_path"]


def entity_names(year_dir):
    """{entity_id: name} for one fiscal year, from the saved entity list."""
    f = year_dir / "entities" / "entity_list.json"
    if not f.exists():
        return {}
    try:
        data = json.load(open(f, encoding="utf-8"))
    except Exception:
        return {}
    return {str(e.get("educationOrganizationId")): e.get("nameOfInstitution", "")
            for e in data if isinstance(e, dict)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    years = sorted(d for d in OUT_DIR.iterdir() if d.is_dir() and d.name.isdigit())
    rows = []
    for ydir in years:
        names = entity_names(ydir)
        files = [p for p in ydir.rglob("*.json") if p.name != "entity_list.json"]
        for p in tqdm.tqdm(files, desc=f"FY{ydir.name}", leave=False):
            rel = p.relative_to(ydir)
            kind = rel.parts[0]
            # state reports sit directly under state/; everything else under <kind>/<id>/
            entity_id = rel.parts[1] if len(rel.parts) > 2 else ""
            rows.append({
                "fiscal_year": ydir.name,
                "entity_id": entity_id,
                "entity_name": names.get(entity_id, "Arizona State Level" if kind == "state" else ""),
                "entity_kind": kind,
                "report": p.stem,
                "url": "",
                "status_code": 200,
                "saved_path": str(p),
            })
        print(f"  FY{ydir.name}: {len(files):,} files")

    print(f"\n{len(rows):,} rows total")
    if args.dry_run:
        return
    with open(OUT_DIR / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT_DIR / 'manifest.csv'}")


if __name__ == "__main__":
    main()
