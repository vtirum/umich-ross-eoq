"""
Ask questions about what data we hold, in plain English.

Builds a small semantic index over the catalogue CSVs (not over the data files
themselves) and answers questions like "which files have 8th grade math scores by
race in Kansas". Two stages:

  build   embed one sentence per catalogued file with a local embedding model
  ask     embed the question, rank by cosine similarity, optionally have the local
          LLM write an answer from the top matches

The index is deliberately built from the catalogue rather than the files. 1,792
files across five states produce a 697 KB catalogue and a ~5 MB index, against
25 GB of underlying data - roughly 0.02%. That is what makes this workable when
the data lives in Drive: the index is small enough to sit next to it, or to be
served from anywhere, and only the answer's file paths need resolving back to
Drive.

    python scripts/common/catalog_search.py build
    python scripts/common/catalog_search.py ask "8th grade math by race in Kansas"
    python scripts/common/catalog_search.py ask "gender breakdowns" --no-llm -k 15

Env:
    EMBED_MODEL=nomic-embed-text   embedding model (Ollama)
    LLM_MODEL=qwen2.5:14b          answer model (see llm_assist.py)
"""

import argparse
import collections
import csv
import glob
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import tqdm

from common import llm_assist as L

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
CATALOG_DIR = Path("data/catalog")
INDEX_PATH = CATALOG_DIR / "_index.jsonl"

STATE_NAMES = {
    "az": "Arizona", "ca": "California", "fl": "Florida", "ga": "Georgia",
    "id": "Idaho", "in": "Indiana", "ks": "Kansas", "ma": "Massachusetts",
    "mi": "Michigan", "mn": "Minnesota", "mo": "Missouri", "ms": "Mississippi",
    "nm": "New Mexico", "nv": "Nevada", "ny": "New York", "pa": "Pennsylvania",
    "ut": "Utah",
}
DIM_NAMES = {"race": "race/ethnicity", "gender": "gender", "iep_504": "special education (IEP/504)",
             "ell": "English learners", "frl": "free/reduced-price meals", "grade": "grade level"}


def _state_of(path):
    parts = Path(path).parts
    if "raw" in parts:
        i = parts.index("raw")
        if i + 1 < len(parts):
            return parts[i + 1]
    return ""


def row_sentence(r):
    """One readable sentence per file - this is what gets embedded."""
    st = STATE_NAMES.get(_state_of(r["path"]), "")
    dims = [DIM_NAMES.get(d, d) for d in (r.get("verified_dims") or "").split("|") if d]
    bits = [f"{st} {r.get('llm_category','')} data" if st else r.get("llm_category", "data")]
    if r.get("llm_topic"):
        bits.append(r["llm_topic"])
    if r.get("years"):
        bits.append("years " + r["years"].replace("|", ", "))
    if r.get("entity_levels"):
        bits.append("at " + r["entity_levels"].replace("|", ", ") + " level")
    if dims:
        bits.append("broken down by " + ", ".join(dims))
    if r.get("columns"):
        bits.append("columns: " + r["columns"].replace("|", ", ")[:300])
    bits.append(Path(r["path"]).name)
    return ". ".join(b for b in bits if b)


def embed(texts, batch=16, verbose=True):
    out = []
    it = range(0, len(texts), batch)
    for start in (tqdm.tqdm(list(it), desc="embedding") if verbose else it):
        for t in texts[start:start + batch]:
            r = requests.post(f"{OLLAMA}/api/embeddings",
                              json={"model": EMBED_MODEL, "prompt": t}, timeout=120)
            r.raise_for_status()
            out.append(r.json()["embedding"])
    return out


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def build():
    rows = []
    for f in sorted(glob.glob(str(CATALOG_DIR / "*.csv"))):
        if Path(f).name.startswith("_"):
            continue
        rows.extend(list(csv.DictReader(open(f, encoding="utf-8"))))
    if not rows:
        print(f"no catalogues in {CATALOG_DIR} - run catalog_local.py first")
        return
    print(f"{len(rows)} catalogued files")
    sentences = [row_sentence(r) for r in rows]
    vecs = embed(sentences)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        for r, s, v in zip(rows, sentences, vecs):
            f.write(json.dumps({
                "path": r["path"], "state": _state_of(r["path"]),
                "category": r.get("llm_category", ""), "topic": r.get("llm_topic", ""),
                "years": r.get("years", ""), "levels": r.get("entity_levels", ""),
                "dims": r.get("verified_dims", ""), "n_rows": r.get("n_rows", ""),
                "size_mb": r.get("size_mb", ""), "text": s, "vec": v,
            }) + "\n")
    print(f"wrote {INDEX_PATH} ({INDEX_PATH.stat().st_size/1e6:.1f} MB)")


ALIAS = {v.lower(): k for k, v in STATE_NAMES.items()}


def resolve_state(s):
    """'ks', 'Kansas', 'kansas' -> 'ks'."""
    s = (s or "").strip().lower()
    return s if s in STATE_NAMES else ALIAS.get(s, s)


def load_index():
    if not INDEX_PATH.exists():
        print("no index - run `build` first")
        return []
    return [json.loads(l) for l in open(INDEX_PATH, encoding="utf-8")]


def apply_filters(items, state=None, category=None, dims=None, level=None):
    """Hard filters, applied before ranking.

    Embedding similarity is a poor state filter: every row's sentence starts with a
    state name, so the vectors sit close together and a question about Kansas happily
    returns Minnesota files at almost the same score. State, category, breakdown and
    entity level are all exact fields in the catalogue - filter on them, and let the
    embedding rank only what is already in scope.
    """
    if state:
        want = {resolve_state(x) for x in state}
        items = [it for it in items if it["state"] in want]
    if category:
        want = {c.lower() for c in category}
        items = [it for it in items if (it.get("category") or "").lower() in want]
    if dims:
        for d in dims:
            items = [it for it in items if d.lower() in (it.get("dims") or "").lower()]
    if level:
        items = [it for it in items if level.lower() in (it.get("levels") or "").lower()]
    return items


def search(question, k=8, **filters):
    items = apply_filters(load_index(), **filters)
    if not items:
        return []
    qv = embed([question], verbose=False)[0]
    scored = sorted(((_cosine(qv, it["vec"]), it) for it in items), key=lambda x: -x[0])
    return scored[:k]


ANSWER_PROMPT = """A researcher asked: "{q}"

These are the most relevant files in our education-data collection. Answer the
question using only what is listed. Say which files to open and what is in them.
If the listing does not cover the question, say so plainly.

{ctx}

Answer in 2-4 sentences, then list the file paths worth opening."""


def ask(question, k=8, use_llm=True, **filters):
    hits = search(question, k, **filters)
    if not hits:
        print("nothing matched those filters")
        return
    scope = ", ".join(f"{k2}={v}" for k2, v in filters.items() if v)
    print(f'\nQ: {question}' + (f'   [{scope}]' if scope else '') + '\n')
    for score, it in hits:
        dims = it["dims"].replace("|", ", ") or "-"
        print(f"  {score:.3f}  [{it['state']}/{it['category']}] {Path(it['path']).name[:52]}")
        print(f"         {it['topic'][:70]}")
        print(f"         dims: {dims} | levels: {it['levels'] or '-'} | rows: {it['n_rows'] or '-'}")
    if not use_llm or not L.available():
        return
    ctx = "\n".join(
        f"- {it['path']} | {it['topic']} | years {it['years'] or '?'} | "
        f"levels {it['levels'] or '?'} | breakdowns {it['dims'] or 'none'} | {it['n_rows']} rows"
        for _, it in hits)
    try:
        resp = L._generate(ANSWER_PROMPT.format(q=question, ctx=ctx), num_predict=400)
        # this prompt wants prose, not JSON, so unwrap if the model returns an object
        try:
            data = json.loads(resp)
            resp = data.get("answer") or data.get("response") or json.dumps(data)
        except ValueError:
            pass
        print("\n--- answer ---")
        print(resp.strip()[:1200])
    except Exception as e:
        print(f"\n(answer model unavailable: {str(e)[:80]})")


SUMMARY_PROMPT = """You are describing one US state's folder in a K-12 education data
collection, for a researcher who has never opened it.

State: {state}
Files: {n}
Folders and what the catalogue says is in them:

{ctx}

Write a short briefing: what this state's data covers, which topics and year ranges are
strong, what entity levels are available, which demographic breakdowns exist, and any
obvious gap. Use only the listing. 6-10 sentences, no bullet points, no preamble."""


def folder_view(items):
    """Group catalogued files by their directory under data/raw/<state>/."""
    folders = {}
    for it in items:
        parts = Path(it["path"]).parts
        i = parts.index("raw") if "raw" in parts else 0
        rel = parts[i + 2:-1] if len(parts) > i + 2 else ()
        key = "/".join(rel) or "."
        f = folders.setdefault(key, {"n": 0, "cats": collections.Counter(),
                                     "dims": collections.Counter(), "levels": collections.Counter(),
                                     "years": set(), "rows": 0, "mb": 0.0, "topics": []})
        f["n"] += 1
        if it.get("category"):
            f["cats"][it["category"]] += 1
        for d in (it.get("dims") or "").split("|"):
            if d:
                f["dims"][d] += 1
        for l in (it.get("levels") or "").split("|"):
            if l:
                f["levels"][l] += 1
        for y in (it.get("years") or "").split("|"):
            if y.isdigit():
                f["years"].add(int(y))
        try:
            f["rows"] += int(it.get("n_rows") or 0)
        except ValueError:
            pass
        try:
            f["mb"] += float(it.get("size_mb") or 0)
        except ValueError:
            pass
        if it.get("topic") and len(f["topics"]) < 4:
            f["topics"].append(it["topic"])
    return folders


def _yr(years):
    return f"{min(years)}-{max(years)}" if years else "-"


def summary(state=None, use_llm=True):
    items = load_index()
    if not items:
        return
    states = [resolve_state(state)] if state else sorted({it["state"] for it in items})
    for st in states:
        sel = [it for it in items if it["state"] == st]
        if not sel:
            print(f"{st}: not catalogued"); continue
        folders = folder_view(sel)
        name = STATE_NAMES.get(st, st)
        print(f"\n{'='*74}\n{name} ({st}) - {len(sel):,} catalogued files, "
              f"{sum(f['mb'] for f in folders.values()):,.0f} MB\n{'='*74}")
        print(f"{'folder':30s} {'files':>6s} {'years':>11s}  top categories / breakdowns")
        lines = []
        for key, f in sorted(folders.items(), key=lambda kv: -kv[1]["n"]):
            cats = ", ".join(f"{c}:{n}" for c, n in f["cats"].most_common(3))
            dims = ",".join(d for d, _ in f["dims"].most_common(5))
            print(f"{key[:30]:30s} {f['n']:>6,} {_yr(f['years']):>11s}  {cats}")
            if dims:
                print(f"{'':30s} {'':>6s} {'':>11s}  dims: {dims}")
            lines.append(f"- {key}: {f['n']} files, years {_yr(f['years'])}, "
                         f"categories {cats or 'none'}, breakdowns {dims or 'none'}, "
                         f"levels {','.join(l for l, _ in f['levels'].most_common(4)) or 'unknown'}, "
                         f"e.g. {'; '.join(f['topics'][:3])}")
        if use_llm and L.available():
            try:
                resp = L._generate(SUMMARY_PROMPT.format(state=name, n=len(sel),
                                                         ctx="\n".join(lines)), num_predict=420)
                print(f"\n--- briefing ---\n{resp.strip()[:1400]}")
            except Exception as e:
                print(f"\n(briefing unavailable: {str(e)[:70]})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "ask", "summary"])
    ap.add_argument("question", nargs="*")
    ap.add_argument("-k", type=int, default=8)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--state", action="append",
                    help="limit to a state, by code or name; repeatable")
    ap.add_argument("--category", action="append", help="assessment, finance, ...")
    ap.add_argument("--dims", action="append", help="race, gender, iep_504, ell, frl")
    ap.add_argument("--level", help="state, county, district, school")
    args = ap.parse_args()
    if args.cmd == "build":
        build()
    elif args.cmd == "summary":
        summary(args.state[0] if args.state else None, use_llm=not args.no_llm)
    else:
        ask(" ".join(args.question), k=args.k, use_llm=not args.no_llm,
            state=args.state, category=args.category, dims=args.dims, level=args.level)


if __name__ == "__main__":
    main()
