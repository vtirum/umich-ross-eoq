"""
Catalogue an API-collected JSON tree as logical datasets, not as files.

The per-file cataloguer (catalog_local.py) reads spreadsheets and CSVs. It skips JSON,
and rightly so: Arizona's report cards are 572,016 JSON files laid out as

    reportcards/<fiscal_year>/<level>/<entity_id>/<report>.json

Cataloguing those one by one would produce half a million near-identical rows and tell
a reader nothing. The tree only has about 700 *logical* datasets - one per
(year, level, report) - each repeated across thousands of entities. This groups them
that way: one row per dataset, with the entity count, how many of those entities
actually returned data, and the record shape read from a sample.

Path layout is inferred rather than hard-coded, so the same tool handles Nevada's
`dashboard/<level>/<org>/<year>.json` and Florida's flatter trees. A path segment that
looks like a year becomes the year, one that is mostly digits becomes the entity, and
the remaining segments name the dataset.

    python scripts/common/catalog_api_tree.py data/raw/az/reportcards --out data/catalog/az_api.csv
    python scripts/common/catalog_api_tree.py data/raw/nv --out data/catalog/nv_api.csv --no-llm
"""

import argparse
import collections
import csv
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tqdm

from common import llm_assist as L
from common.catalog_local import VALID_CATEGORIES, _scrub_topic

YEAR_SEG = re.compile(r"^(19|20)\d{2}(-\d{2,4})?$")
ID_SEG = re.compile(r"^[A-Za-z]{0,3}\d{2,}$")
LEVELS = {"state", "district", "school", "county", "lea", "entities", "unknown"}
SAMPLE_PER_GROUP = 40


def classify_segments(rel_parts):
    """Split a path into (year, level, entity, dataset-name-parts)."""
    year = level = entity = ""
    name = []
    for seg in rel_parts:
        low = seg.lower()
        if not year and YEAR_SEG.match(Path(seg).stem):
            year = Path(seg).stem
        elif not level and low in LEVELS:
            level = low
        elif not entity and ID_SEG.match(seg):
            entity = seg
        else:
            name.append(Path(seg).stem if seg is rel_parts[-1] else seg)
    return year, level, entity, "/".join(name)


def record_shape(path, cap=12):
    """Top-level keys of the first record, plus whether the payload is empty."""
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        return [], True, 0
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v:
                data = v
                break
    if not isinstance(data, list):
        return (sorted(data)[:cap] if isinstance(data, dict) else []), not data, 1
    if not data:
        return [], True, 0
    first = data[0]
    keys = sorted(first)[:cap] if isinstance(first, dict) else []
    return keys, False, len(data)


CAT_PROMPT = """You are cataloguing datasets pulled from a US state's K-12 education API.
Each entry is one logical dataset: its name, the entity level it covers, and the field
names of one record. Classify from the FIELDS, not the name alone.

For each numbered dataset return:
  "n"        its number
  "category" exactly one of: {cats}
  "topic"    a short human label, max 8 words. Name an assessment programme only if
             that name appears in the dataset's own name or fields.

Return ONLY JSON: {{"results":[ ... ]}}

DATASETS:
{items}"""


def classify(groups, batch=14, verbose=True):
    out = {}
    keys = list(groups)
    for start in tqdm.tqdm(range(0, len(keys), batch), desc="classifying", disable=not verbose):
        chunk = keys[start:start + batch]
        items = []
        for i, k in enumerate(chunk, 1):
            g = groups[k]
            items.append(f"{i}. dataset: {g['dataset']}\n"
                         f"   level: {g['level'] or '?'}   entities: {g['entities']}\n"
                         f"   fields: {', '.join(g['fields'][:12]) or 'unknown'}")
        try:
            data = L._parse_json(L._generate(
                CAT_PROMPT.format(cats=", ".join(sorted(VALID_CATEGORIES)),
                                  items="\n".join(items)), num_predict=1200))
        except Exception as e:
            if verbose:
                tqdm.tqdm.write(f"  batch @{start} failed: {str(e)[:60]}")
            continue
        results = (data or {}).get("results") if isinstance(data, dict) else data
        if not isinstance(results, list):
            continue
        for rec in results:
            if not isinstance(rec, dict):
                continue
            try:
                n = int(rec.get("n", 0)) - 1
            except (TypeError, ValueError):
                continue
            if not (0 <= n < len(chunk)):
                continue
            g = groups[chunk[n]]
            cat = str(rec.get("category", "other")).lower().strip()
            out[chunk[n]] = {
                "category": cat if cat in VALID_CATEGORIES else "other",
                "topic": _scrub_topic(str(rec.get("topic", ""))[:90],
                                      {"name": g["dataset"], "sheets": [],
                                       "columns": g["fields"]}),
            }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    root = Path(args.root)
    files = [p for p in root.rglob("*.json")]
    print(f"{len(files):,} JSON files under {root}")

    groups = {}
    for p in tqdm.tqdm(files, desc="grouping"):
        year, level, entity, name = classify_segments(p.relative_to(root).parts)
        key = (name, level, year)
        g = groups.setdefault(key, {
            "dataset": name, "level": level, "year": year,
            "entities": 0, "nonempty": 0, "bytes": 0, "paths": [], "fields": [], "rows": 0})
        g["entities"] += 1
        g["bytes"] += p.stat().st_size
        if p.stat().st_size > 3:
            g["nonempty"] += 1
            if len(g["paths"]) < SAMPLE_PER_GROUP:
                g["paths"].append(p)
    print(f"{len(groups):,} logical datasets")

    rng = random.Random(0)
    for g in tqdm.tqdm(groups.values(), desc="sampling shapes"):
        for p in rng.sample(g["paths"], min(3, len(g["paths"]))):
            keys, empty, n = record_shape(p)
            if keys:
                g["fields"] = keys
                g["rows"] = max(g["rows"], n)
                break

    labels = {} if args.no_llm else classify(groups)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["path", "size_mb", "sheets", "n_cols", "n_rows", "columns", "years",
                    "llm_category", "llm_topic", "llm_confidence", "entity_levels",
                    "verified_dims", "dims_source", "entities_with_data"])
        for key, g in sorted(groups.items()):
            lab = labels.get(key, {})
            # `path` is the group's directory pattern, not a single file - it is what a
            # reader needs to find the data, and keeps the schema identical to the
            # per-file catalogue so both feed one index.
            pat = str(root / (g["year"] or "*") / (g["level"] or "*") / "*" /
                      f"{g['dataset']}.json")
            w.writerow([pat, round(g["bytes"] / 1e6, 2), "", len(g["fields"]),
                        g["entities"], "|".join(g["fields"]), g["year"],
                        lab.get("category", ""), lab.get("topic", ""), "",
                        g["level"], "", "api_tree", g["nonempty"]])
    dead = sum(1 for g in groups.values() if g["nonempty"] == 0)
    print(f"wrote {args.out}: {len(groups):,} rows "
          f"(from {len(files):,} files, {sum(g['bytes'] for g in groups.values())/1e9:.1f} GB)")
    if dead:
        print(f"  {dead} datasets returned no data for any entity - the endpoint exists "
              f"but is empty, which is worth knowing before anyone goes looking")


if __name__ == "__main__":
    main()
