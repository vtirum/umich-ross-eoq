"""
Local-LLM helpers (Ollama) for labelling data files.

Keyword rules mis-file a lot of state DOE data. 
A small local model reads the human-written link text and does much better.

    ollama serve
    ollama pull qwen2.5:14b        # or set LLM_MODEL

classify_files()  category + demographic dimensions per file label
rank_pages()      which page links are worth crawling for bulk data

Both batch their input (one call per ~25 items) and cache to data/cache/llm, so
re-runs are free. Link extraction stays deterministic; the model only labels and
prioritises, and its output is constrained to a fixed category set.

Caveat: dimensions guessed from a title are unreliable in both directions. Use
verify_dims.py for anything that matters.
"""

import hashlib
import json
import os
import re
from pathlib import Path

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("LLM_MODEL", "qwen2.5:14b")
CACHE_DIR = Path("data/cache/llm")
BATCH = int(os.environ.get("LLM_BATCH", "25"))

CATEGORIES = ["assessment", "enrollment", "attendance", "graduation",
              "discipline", "staff", "finance", "directory", "other"]
DEMOG_DIMS = ["race", "gender", "iep_504", "ell", "frl", "grade", "none"]


def available():
    """True if an Ollama server with the configured model is reachable."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        names = [m.get("name", "") for m in r.json().get("models", [])]
        return any(n.split(":")[0] == MODEL.split(":")[0] for n in names)
    except Exception:
        return False


def _cache_path(key):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{hashlib.sha256(key.encode()).hexdigest()[:20]}.json"


def _generate(prompt, num_predict=1600):
    cp = _cache_path(MODEL + prompt)
    if cp.exists():
        try:
            return json.loads(cp.read_text())["response"]
        except Exception:
            pass
    r = requests.post(f"{OLLAMA_URL}/api/generate", json={
        "model": MODEL, "prompt": prompt, "stream": False, "format": "json",
        "options": {"temperature": 0, "num_predict": num_predict},
    }, timeout=600)
    r.raise_for_status()
    resp = r.json()["response"]
    cp.write_text(json.dumps({"response": resp}))
    return resp


def _parse_json(text):
    """Ollama's format=json is usually clean, but be forgiving."""
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}|\[.*\]", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


CLASSIFY_PROMPT = """You label public K-12 education data files from a US state education agency.

For each numbered file, using its title (and URL hint), return:
  "n"        the file's number
  "category" exactly one of: {cats}
  "dims"     which demographic breakdowns the file's title indicates it contains,
             any of: {dims}. Use ["none"] if the title shows no breakdown.
  "year"     4-digit year if one appears in the title, else null

Guidance:
- "category" describes the SUBJECT of the data, not the file format.
- assessment = test/exam results (MCA, ILEARN, IREAD, MAP, SAT, ACT, WIDA, ACCESS, EOC, proficiency).
- enrollment = student counts, membership, demographics, free/reduced-price meals counts.
- attendance = attendance rate, absenteeism, ADA/ADM, mobility.
- staff = teachers, faculty, educators, certification, salary, personnel, staff ratios.
- finance = expenditures, revenue, per-pupil spending, budgets, funding, valuation, tax levy.
- directory = school/district lists, contact info, org codes, maps.
- discipline = suspensions, expulsions, incidents, referrals, safety.
- graduation = graduation/dropout/cohort/completion/college-going.
- dims: mark "race" for race/ethnicity, "iep_504" for special education/disability/IEP/504,
  "ell" for English learner/EL/ELL/LEP/limited English, "frl" for free/reduced-price meals
  when used as a reported subgroup, "gender" for male/female/sex, "grade" for by-grade-level.
  Words like "disaggregated", "by student group", "subgroup" mean breakdowns are present —
  list every dimension the title names, and if it says only "disaggregated"/"by student group"
  without naming them, use ["race","gender","iep_504","ell"].

Return ONLY a JSON object: {{"results": [ ... one object per file ... ]}}

FILES:
{files}"""


def classify_files(items, batch=BATCH, verbose=False):
    """items: [{'label': str, 'url': str (optional)}]. Returns list aligned to items:
    [{'category':..., 'dims':[...], 'year':int|None}] (None entry if the model failed)."""
    out = [None] * len(items)
    for start in range(0, len(items), batch):
        chunk = items[start:start + batch]
        lines = []
        for i, it in enumerate(chunk):
            hint = ""
            url = (it.get("url") or "")
            if url:
                tail = re.sub(r"https?://[^/]+/", "", url)[:70]
                hint = f"   [url: {tail}]"
            lines.append(f"{i+1}. {str(it.get('label',''))[:150]}{hint}")
        prompt = CLASSIFY_PROMPT.format(cats=", ".join(CATEGORIES),
                                        dims=", ".join(DEMOG_DIMS),
                                        files="\n".join(lines))
        try:
            data = _parse_json(_generate(prompt))
        except Exception as e:
            if verbose:
                print(f"    llm batch @{start} failed: {str(e)[:80]}")
            continue
        if not data:
            continue
        results = data.get("results") if isinstance(data, dict) else data
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
            cat = str(rec.get("category", "other")).lower().strip()
            if cat not in CATEGORIES:
                cat = "other"
            dims = rec.get("dims") or []
            if isinstance(dims, str):
                dims = [dims]
            dims = [str(d).lower().strip() for d in dims if str(d).lower().strip() in DEMOG_DIMS]
            dims = [d for d in dims if d != "none"]
            year = rec.get("year")
            try:
                year = int(year) if year else None
            except (TypeError, ValueError):
                year = None
            out[start + n] = {"category": cat, "dims": dims, "year": year}
        if verbose:
            done = sum(1 for x in out if x)
            print(f"    llm classified {done}/{len(items)}")
    return out


RANK_PROMPT = """You are helping a researcher find DOWNLOADABLE BULK DATA FILES on a US state
education agency website. Given links from one page, decide which are worth opening next.

Score each link 0-3:
  3 = very likely leads to downloadable data files (e.g. "Data downloads", "Assessment results",
      "Enrollment data", "Statistics", "Data files", "Archive", "Reports and data")
  2 = plausibly a data/reports section worth checking
  1 = probably informational (guidance, policy, news, program description)
  0 = clearly irrelevant (login, contact, careers, social media, accessibility, calendar)

Return ONLY JSON: {{"results":[{{"n":1,"score":3}}, ...]}}

LINKS:
{links}"""


def rank_pages(links, batch=BATCH, verbose=False):
    """links: [{'text':..., 'url':...}] -> list of int scores (0-3), 1 if unknown."""
    scores = [1] * len(links)
    for start in range(0, len(links), batch):
        chunk = links[start:start + batch]
        lines = [f"{i+1}. {str(l.get('text',''))[:90]}  [{re.sub(r'https?://[^/]+', '', l.get('url',''))[:80]}]"
                 for i, l in enumerate(chunk)]
        try:
            data = _parse_json(_generate(RANK_PROMPT.format(links="\n".join(lines)), num_predict=900))
        except Exception:
            continue
        if not data:
            continue
        results = data.get("results") if isinstance(data, dict) else data
        if not isinstance(results, list):
            continue
        for rec in results:
            if not isinstance(rec, dict):
                continue
            try:
                n = int(rec.get("n", 0)) - 1
                sc = int(rec.get("score", 1))
            except (TypeError, ValueError):
                continue
            if 0 <= n < len(chunk):
                scores[start + n] = max(0, min(3, sc))
        if verbose:
            print(f"    llm ranked {min(start+batch, len(links))}/{len(links)}")
    return scores
