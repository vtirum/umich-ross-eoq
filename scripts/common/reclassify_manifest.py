"""
Re-label an existing download manifest with the local LLM.

Adds llm_category and llm_dims columns to a copy of the manifest
(<manifest>_llm.csv); the original is untouched. Keyword categorisation is coarse
- our Missouri crawl filed 54% of files as "other", which this cuts to 4%.

For demographic dimensions prefer verify_dims.py, which reads the files rather
than their titles.

    python scripts/common/reclassify_manifest.py data/raw/mo/mcds/manifest.csv
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import llm_assist as L


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    src = Path(sys.argv[1])
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    if not rows:
        print("empty manifest")
        return
    if not L.available():
        print(f"Ollama/{L.MODEL} not available — start `ollama serve` first.")
        return

    label_key = "label" if "label" in rows[0] else next(
        (k for k in ("doc", "name", "title") if k in rows[0]), None)
    url_key = next((k for k in ("file_url", "url", "wayback_url") if k in rows[0]), None)
    items = [{"label": r.get(label_key, ""), "url": r.get(url_key, "") if url_key else ""}
             for r in rows]

    print(f"{src}: {len(items)} files -> {L.MODEL}")
    res = L.classify_files(items, verbose=True)

    for r, c in zip(rows, res):
        r["llm_category"] = c["category"] if c else ""
        r["llm_dims"] = "|".join(c["dims"]) if c and c["dims"] else ""

    dest = src.with_name(src.stem + "_llm.csv")
    fields = list(rows[0].keys())
    with open(dest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    cats = Counter(r["llm_category"] for r in rows if r["llm_category"])
    demog = [r for r in rows if r["llm_dims"]]
    print(f"\nwrote {dest}")
    print("llm categories:", dict(cats.most_common()))
    print(f"files with demographic breakdowns: {len(demog)}")
    dims = Counter(d for r in demog for d in r["llm_dims"].split("|"))
    print("dimensions:", dict(dims.most_common()))


if __name__ == "__main__":
    main()
