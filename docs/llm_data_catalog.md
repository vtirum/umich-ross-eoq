# Making an LLM know what's in the data folder

Notes for the central IT team, from the EOQ education-data collection.
Everything below has been built and measured on a real corpus, not proposed in
the abstract. Code is in `scripts/common/`.

## The problem

We hold **611,809 files, 36 GB, across 17 states**. Nobody can answer "do we have
8th-grade math scores broken out by race for Kansas?" without opening folders. The
filenames are frequently no help: Minnesota's download handler names 115 of its
files `000574.xlsx`, `000722.xlsx`, and so on.

The instinct is to feed the files to an LLM. That is the wrong shape. Files are
large, mostly numeric, and the question is nearly always *which file*, not *what
is the number*.

## What we built instead

Three stages, each cheap, each separately useful.

### 1. Content signature (deterministic, no model)

`catalog_local.py` walks a directory and for each file records sheet names, header
columns, a sample of values, row count and any years found. From that it also
derives, by pattern-matching the columns:

- `entity_levels` — state / county / district / school
- `verified_dims` — race, gender, IEP/504, EL, free-reduced meals

**Measured:** 788 files in 30 seconds. Handles xlsx, legacy .xls (via xlrd - openpyxl
cannot read BIFF), csv, tsv.

### 2. Classification (local LLM)

The same tool sends the signature - not the file - to a local model
(Ollama, qwen2.5:14b) for a category and a one-line topic. Roughly 12 files per
call, ~60s per call.

### 3. Retrieval (local embeddings)

`catalog_search.py` turns each catalogue row into one sentence, embeds it with
`nomic-embed-text`, and answers questions by cosine similarity, optionally passing
the top matches to the LLM to write a short answer.

**Measured:** 1,792 files embedded in 35 seconds; queries return in under a second.

### 4. Folder structure, not just files

Two additions came out of trying to answer "what does Arizona actually have?".

`catalog_search.py summary --state arizona` groups the catalogue by folder and prints
files, year span, categories, entity levels and demographic breakdowns per folder, then
has the local model write a short briefing from that table. It is the fastest way to
orient someone who has never opened a state's folder.

`catalog_api_tree.py` handles the API-collected JSON trees, which the per-file
cataloguer skips by design. Arizona's report cards are **572,216 JSON files** laid out
as `<year>/<level>/<entity>/<report>.json` — cataloguing them one by one would produce
half a million near-identical rows. They are really only **752 logical datasets**, one
per (year, level, report), each repeated across thousands of entities:

| state | JSON files | logical datasets | ratio |
|---|---|---|---|
| Arizona report cards | 572,216 (10.5 GB) | 752 | 0.13% |
| Nevada | 9,147 | 52 | 0.57% |

Each row carries the field names, the entity count and how many of those entities
actually returned data. That last number matters: **188 of Arizona's 752 datasets are
empty for every entity** — the endpoint exists and returns `[]`. Knowing that up front
saves someone a day of looking for data that was never published.

## What the testing showed

### It works, including on unnamed files

    $ catalog_search.py ask "Minnesota reading test scores by student group in the 2000s"
      0.749  [mn/assessment] MCAMTAS_Reading_NonPublic_Oct2025.xlsx
      0.743  [mn/assessment] 000969.xlsx   MCA math and reading scores by demographic
      0.742  [mn/assessment] 000730.xlsx   Test results by student group

`000730.xlsx` is findable by describing what is in it. That is the whole point.

    $ catalog_search.py ask "which states have gender breakdowns in graduation data"
      0.758  [nm/graduation] ACC_Webfiles_2007_GraduationRates.xls
             dims: ell, frl, gender, iep_504, race | state level | 286 rows
      0.754  [mn/graduation] 2024-25_Graduates.xlsx

### It surfaced a real coverage gap we had missed

Asked for "8th grade math proficiency by race in Kansas", the search returned
enrollment files. That was not a retrieval failure: **Kansas had zero assessment
files** in our collection at the time. KSDE's 19 reports cover attendance, graduation,
enrollment, discipline and staff, but not test scores — those live in a separate KSDE
system, which we then went and collected (2.2M rows, school level, 2015-2025). The
catalogue found the hole before a human did, which is the strongest argument for
building one. The
answer layer said so correctly ("these files do not directly contain math
proficiency data").

### The LLM is good at labelling and bad at claims about content

This is the most important lesson for anyone building on this. We asked the model
which demographic breakdowns each file contained, judging from its title, then
checked every answer against the file itself:

| | agreed | over-claimed | **missed** |
|---|---|---|---|
| Indiana | 142 | 2 | **154** |
| Missouri | 66 | 2 | **43** |

It missed 154 Indiana files that genuinely carry breakdowns. Titles are not
evidence, in either direction. Two further cases of the same failure mode:

- It labelled a 33,706-row data extract a "blank format template" because the
  column names read like a specification. Fixed with a row-count rule, not a
  better prompt.
- Asked for entity levels, it returned blank on files whose headers plainly said
  `District` and `School`. Moved to a regex.

Where it genuinely helps: categorisation. Keyword rules put **54% of Missouri's
files in "other"; the model cut that to 4%**.

**Design rule we settled on: the model proposes, deterministic code decides.**
Anything checkable is checked in code, and the catalogue keeps the two in separate
columns (`llm_*` vs `verified_*`) so a consumer knows which is which.

### Known weaknesses

- The answer layer will stretch. Given only enrollment files it suggested they
  "could be used to infer math proficiency trends by race" - they cannot. Answers
  need the retrieved rows shown alongside, which is why the CLI prints them.
- `verified_dims` detects demographic *columns*, so a blank submission template
  with a `Gender` field matches. Pair it with row count.
- Entity-level detection under-reads some legacy layouts where the geography sits
  in a header block above the column row.
- PDFs are skipped entirely. That is most of Idaho's and Mississippi's apparent
  gaps.
- No labelled evaluation set yet. Retrieval quality is assessed by inspection,
  which is fine for a prototype and not fine for a production claim.

## Does this work if the data lives in Dropbox?

Yes, and the shape of the answer is the same as for Drive: **the index is built from the
catalogue, not from the data**, so what has to travel is tiny.

| | size |
|---|---|
| Underlying data | ~37 GB |
| Catalogue CSVs | ~1 MB |
| Embedding index | ~30 MB |

*(Measured on this corpus. The Dropbox mechanics below are reasoned from the API docs,
not measured — we have not yet run it against a real Dropbox.)*

**The easy path: let the desktop client do the work.** If the folder is synced locally
by the Dropbox app, `catalog_local.py` needs no changes at all — point it at
`~/Dropbox/eoq-data` and everything in this document applies unchanged.

One trap: **online-only files**. With Smart Sync / "online-only", files appear in the
filesystem as placeholders. A cataloguer that reads the first rows will either force a
slow download per file or read a stub. Before a big run, either set the folder to
"Local" (`Make available offline`), or check `st_blocks` and skip anything that is a
placeholder rather than silently cataloguing an empty file.

**The API path.** `/2/files/list_folder` (plus `/continue` for paging) returns path,
size, `id`, `rev` and `content_hash` with no download. That is enough for the structural
half of the catalogue. Reading *columns* means bytes: `/2/files/download` streams a file,
and CSVs can be truncated early, but an `.xlsx` is a zip and has to come down whole.

Two things Dropbox does better than Drive here:

- **`content_hash` is free and deterministic** — a documented SHA-256-of-4MB-blocks
  scheme. Store it per row and re-cataloguing becomes a hash comparison; nothing is
  re-read unless its bytes actually changed. Drive has no equivalent that avoids a read.
- **`/2/files/list_folder/longpoll`** pushes changes, so an incremental job can be
  event-driven instead of a nightly full walk.

**Store the Dropbox `id:` alongside the path.** Paths break when folders are
reorganised; the file ID survives moves and renames, and lets an answer link straight to
the file. This is the single most important change to make before loading the data in.

Watch for: per-app rate limits (catalogue in batches, keep the job resumable — `catalog_local.py`
skips any file whose path and byte size match the existing catalogue, so a re-run only
pays for what changed; `--full` forces a redo); shared-folder permissions, which the API inherits, so a
folder the running account cannot see will silently not appear; and team folders, which
need the `Dropbox-API-Path-Root` header or paths will not resolve.

## Does this work if the data lives in Google Drive?

Yes, and Drive is arguably a better fit than local disk, because **the index is
built from the catalogue, not from the data**.

| | size |
|---|---|
| Underlying data (5 states catalogued so far) | ~8 GB |
| Catalogue CSVs | 697 KB |
| Embedding index | 29.8 MB |

The index is about 0.4% of the data, and the catalogue itself is 0.01%.
Extrapolated to all 112k files, expect a catalogue of roughly 40 MB and an index
around 2 GB — or far less with a smaller embedding model or quantisation.

Two ways to run it:

**A. Catalogue once, ship the index.** Signature extraction needs to read each
file's first rows, so it wants the bytes once. Do that wherever the files already
are, then the resulting catalogue and index are small enough to live anywhere -
next to the Drive folder, in a repo, behind a web service. Re-catalogue only new
files; everything is keyed by path.

**B. Native Drive.** The Drive API lists files and metadata with no download at
all, which is enough for path, name, size and modified time. Reading *columns*
means fetching file bytes: `files.get?alt=media` streams, and for CSV a range
request over the first few KB is sufficient. Spreadsheets need the whole file
because the format is a zip, so budget one full read per xlsx. A Colab notebook
with Drive mounted is the least-effort version of this.

**One change to make if you go the Drive route:** store the Drive **file ID**
alongside `path` in the catalogue. Paths break when folders are reorganised; file
IDs are stable, and they let an answer link straight to the document.

Practical notes: Drive API has per-user rate limits, so catalogue in batches and
make the job resumable (ours skips anything already catalogued). Shared-drive
permissions are inherited by the API - if the person running the job cannot see a
folder, it silently will not appear in the catalogue.

## What we would suggest for a production version

1. **Keep the two-signal split.** `llm_*` for judgment, `verified_*` for facts.
   Consumers should filter on the verified columns.
2. **Store file IDs, not just paths.**
3. **Build an evaluation set** — 50 or so real questions with known-correct file
   answers — before claiming accuracy. We have not done this.
4. **Incremental cataloguing** — built, keyed on path + byte size (not mtime, which
   cloud sync rewrites on unchanged files). In Dropbox, key it on `content_hash`
   instead: it is returned free by `list_folder` and changes only when bytes change.
5. **A smaller embedding model is probably fine.** `all-minilm` would cut the
   index roughly 4x; worth measuring against the eval set rather than assuming.
6. **Keep it local if the data is sensitive.** Everything here runs on a laptop
   via Ollama; no data leaves the machine, which sidesteps the question of
   student-level data and third-party APIs entirely. Our corpus is public and
   privacy-suppressed at source, but that will not be true of every dataset the
   university holds.

## Reproducing this

```bash
ollama serve && ollama pull qwen2.5:14b && ollama pull nomic-embed-text

# per-file catalogue (spreadsheets and CSVs)
python scripts/common/catalog_local.py data/raw/mn --out data/catalog/mn.csv

# API JSON trees, grouped into logical datasets
python scripts/common/catalog_api_tree.py data/raw/az/reportcards --out data/catalog/az_api.csv

python scripts/common/catalog_search.py build

# ask, scoped to a state - filters are exact, the embedding only ranks what is in scope
python scripts/common/catalog_search.py ask "8th grade math by race" --state kansas
python scripts/common/catalog_search.py ask "teacher salaries" --state az --category staff
python scripts/common/catalog_search.py ask "graduation" --dims gender --level school

# what is in a state's folder, and how it is organised
python scripts/common/catalog_search.py summary --state arizona
```

`--no-llm` on the cataloguer gives signatures, entity levels and verified
dimensions with no model involved — the full 25 GB in a few minutes, and enough on
its own to answer "which files have gender at school level".

Relevant code: `catalog_local.py`, `catalog_search.py`, `verify_dims.py`,
`llm_assist.py`.
