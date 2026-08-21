# UMich Ross EOQ Education Data Pipeline

Automated collection of publicly available K-12 education data across 17 states. Covers assessments, enrollment, finance, teacher/staff records, and discipline/suspension data at the state, district, and school level. Designed to be reproducible and extensible to all 50 states.

## States Covered

| State | Primary Sources | Method |
|---|---|---|
| **Arizona** | AZ Report Cards API, ADE accountability pages, finance portal | API + Static + Browser |
| **Florida** | edudata.fldoe.org (Tableau API), FL Report Cards API, FLDOE static | API + Dashboard |
| **California** | cde.ca.gov bulk downloads, CAASPP assessment files, DataSF/Oakland Open Data | Static (stealth browser for captcha) + Socrata API |
| **Utah** | schools.utah.gov/datastatistics/reports.php, Utah Open Data | Static + Socrata API |
| **Nevada** | nevadareportcard.nv.gov API (assessment), doe.nv.gov topic pages | API + Static |
| **Massachusetts** | profiles.doe.mass.edu (ASP.NET postback), doe.mass.edu/infoservices | Static (form replication) |
| **New York** | data.nysed.gov (MS Access DB per year) | Static |
| **Georgia** | download.gosa.ga.gov, GaDOE Insights (Azure blob) | Static + Dashboard |
| **Pennsylvania** | futurereadypa.org data files, PDE reports | Static |
| **Michigan** | mischooldata.org CDN files, legacy ASP.NET dashboard | Static + Browser |
| **Minnesota** | pub.education.mn.gov MDE Analytics (file listers), rc.education.mn.gov API | Static + API |
| **Kansas** | datacentral.ksde.gov report generator, ksreportcard.ksde.gov full-file workbooks + service | Form replication + Static + API |
| **Mississippi** | mdek12.org/publicreporting (per-year + topic pages) | Static |
| **New Mexico** | web.ped.nm.gov accountability + directory pages | Static |
| **Idaho** | sde.idaho.gov finance-transparency, idahoreportcard.org export API | Static + API |
| **Missouri** | apps.dese.mo.gov/MCDS (Missouri Comprehensive Data System bulk files) | Static |
| **Indiana** | in.gov/doe/it/data-center-and-reports (IDOE Data Center bulk files) | Static |

**Federal supplements (all states):**
- `scripts/crdc/` — CRDC discipline, enrollment, and staff (covers every state)
- `scripts/census_f33/` — Census F-33 district finance survey (fills gaps where state finance sources are blocked)

## Data Categories

All five categories are covered for all 17 states:

- **Assessment** — ELA, Math, Science, ACT, SAT, AP, SBAC, MCAS, M-STEP, etc.
- **Financial** — per-pupil expenditure, revenue/expenditure by fund, SACS, F-33
- **Enrollment** — by grade, race/gender, special populations, SPED, CTE
- **Discipline/Suspension** — state-reported + CRDC federal supplement
- **Teacher/Staff** — salaries, race/gender, qualifications, grade/subject assignments

## Repository Structure

```
umich-ross-eoq/
  requirements.txt
  README.md
  docs/
    coverage_matrix.md       # per-state source detail, methods, known gaps
  scripts/
    common/                  # shared utilities used by all state scripts
      http_client.py         # requests session with retry/backoff
      file_utils.py          # safe filenames, sha256, file type helpers
      manifest.py            # manifest CSV writer (skip-existing + tracking)
      playwright_capture.py  # shared Playwright browser setup
      static_site.py         # generic crawl+download engine (ID, MS, NM)
      powerbi.py             # Power BI DSR capture/decode (AZ, IN)
      llm_assist.py          # local-LLM classification (Ollama)
      verify_dims.py         # deterministic demographic-column detection
      catalog_local.py       # catalogue files already on disk, from their contents
      site_audit.py          # crawl + diff vs manifest to find missed files
    az/ ca/ fl/ ga/            # one directory per state
    id/ in/ ks/ ma/ mi/
    mn/ mo/ ms/ nm/ nv/
    ny/ pa/ ut/
    census_f33/              # federal district finance (all states)
    crdc/                    # federal discipline/enrollment/staff (all states)
  data/
    raw/                     # downloaded files (not committed — share via Drive)
      az/
      ca/
      fl/
      ...
```

Downloaded data is not stored in GitHub (too large). Share the `data/raw/` folder separately via Google Drive or similar.

## Setup

Requires Python 3.12+.

```bash
git clone https://github.com/vtirum/umich-ross-eoq.git
cd umich-ross-eoq

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

On Linux, replace the last line with:
```bash
playwright install --with-deps chromium
```

## Running the Scripts

Activate the virtual environment first:
```bash
source .venv/bin/activate
```

All scripts are run from the repo root and write output to `data/raw/<state>/`.

### Arizona
```bash
python scripts/az/azed_data_pages.py            # the three file-bearing pages under the
                                               #   Public Data Sets hub: accountability
                                               #   (assessment/graduation/dropout/Oct-1
                                               #   enrollment), hns/frp (free & reduced-price
                                               #   percentages), sppapr (IDEA indicator
                                               #   profiles incl. Ind 4 suspension)
python scripts/az/report_cards_reports.py      # report cards API, FY2018-2025
                                               #   (AZ_RC_YEARS=2019,2020 narrows a run)
python scripts/az/finance_static_download.py   # static finance files
python scripts/az/finance_dynamic_download.py  # dynamic finance portal (Playwright)
python scripts/az/workforce_dashboards.py      # ADE Workforce (Power BI): teacher race, gender,
                                               #   education, experience, county + 2019-2026 trends
```

`azed.gov/data/public-data-sets` is a hub page — it holds one PDF and links out to the
pages that actually publish files. Crawling only `accountability-research/data` (which is
what we did at first) misses free/reduced-price lunch and the IDEA indicator profiles
entirely, so `azed_data_pages.py` seeds from all three.

Two bugs worth remembering, both found in an audit rather than at runtime:

- **Handler URLs collide.** The accountability page used to serve files through
  `.../GetDocumentFile?id=N`. Naming downloads after the URL's last path segment gave all
  of them the name `GetDocumentFile`, so each overwrote the last — **69 files reduced to
  one**, and because the next run saw that file already on disk it recorded all 69 as
  `skipped_existing`. Nine years of graduation cohorts, five of dropout and six of Oct-1
  enrollment were missing while the manifest read 132/132 clean. `static_site.choose_dest`
  now falls back to the link text whenever the basename is generic, and refuses to let two
  URLs claim one path.
- **HTML saved as data.** Failed fetches returned a 536-byte Cloudflare page with a 200,
  which got written as `.pdf` and hashed into the manifest as a success.
  `static_site.looks_like_html` now rejects those, and 12 were cleared out of `data/raw/az/`.

The report cards API serves FY2018-2025; the script used to take only the most recent
year (`fiscal_years[-1:]`), leaving six years unfetched. All eight are now on disk
(~11 GB, ~71,500 JSON files per year across state, 15,111 district and 56,373 school
entities). A third of each year is `[]` — an endpoint with nothing to report for that
entity — rising to about 70% in the older years.

- **Scoped runs used to truncate the manifest.** `IncrementalManifest` opened its file
  with `"w"`, so a run limited to one fiscal year left a manifest describing only that
  year while eight years of data sat on disk. It now reads prior rows and writes them
  back before appending, and `finalize()` collapses duplicates on a caller-supplied key
  so a re-run updates a row instead of doubling it. Five scripts share the class (AZ, FL,
  and three NV). `scripts/az/rebuild_reportcards_manifest.py` reconstructs the AZ manifest
  from the tree rather than re-downloading 11 GB to regenerate it.

Checked and deliberately skipped: `azed.gov/cte/data` — 134 files, but bulk-upload
templates, user guides and policy PDFs rather than data.

### Florida
```bash
python scripts/fl/scrape.py            # static FLDOE data pages
python scripts/fl/report_cards.py      # FL report cards API (includes GetTGELA: assessment by gender/race/IEP/ELL)
python scripts/fl/edudata_export.py    # Tableau/edudata API
python scripts/fl/fldoe_download.py    # fldoe.org bulk files via Wayback proxy (Akamai blocks direct):
                                       #   attendance, enrollment, staff, graduation, 2025 FAST
```

### California
```bash
python scripts/ca/download.py               # bulk CDE data files (assessment, enrollment, staff, finance, school directory)
python scripts/ca/assessment_download.py    # CAASPP/ELPAC statewide assessment research files
python scripts/ca/local_portals_download.py # DataSF + Oakland Open Data (Tier-L local portals)
```

### Utah
```bash
python scripts/ut/download.py                 # USBE reports page bulk Excel/PDF downloads
python scripts/ut/opendata_download.py        # Utah Open Data (opendata.utah.gov) USBE-owned datasets
python scripts/ut/datagateway_proficiency.py  # Data Gateway (Tableau): proficiency by demographic
                                              #   group incl. gender, which the static reports omit
```

### Nevada
```bash
python scripts/nv/download.py            # NV Report Card API — 6 assessments (All Students):
                                         #   SBAC ELA/Math 3-8, CCR Grade 11, Science 5/8,
                                         #   Science 9/10, NAA (alternate), ELPA
python scripts/nv/subgroups_download.py  # same 6 assessments by race/ethnicity, gender, IEP, EL, FRL
python scripts/nv/reportcard_full.py     # extended NV report card categories
python scripts/nv/doe_download.py        # doe.nv.gov topic pages (enrollment, finance, staff, CTE)
python scripts/nv/reorganize.py          # one-off tidy-up of data/raw/nv (idempotent)
```
Nevada's output grew across several scripts and needed flattening. `reorganize.py`
consolidates the report card's **9,061 single-record JSON files into one
`reportcard/dashboard.csv`** (9,061 rows x 69 columns, state/district/school,
2014-2025), moves the twelve one-file `assessment_*` directories into
`assessment/<exam>.csv`, merges the five per-script manifests into `manifest_all.csv`,
and clears empty directories. Raw JSON is kept alongside the CSV; the only deletions
are empty directories and `.DS_Store`.

`reportcard/detail/` stays as JSON on purpose — its rows are headerless `cells`
arrays and the column names appear neither in the payload nor the manifest, so a CSV
conversion would invent meaningless headers.

### Massachusetts
```bash
python scripts/ma/download.py                  # profiles.doe.mass.edu statewide reports (ASP.NET postback)
python scripts/ma/mcas_subgroups.py            # MCAS by race/ethnicity, gender, IEP, EL (ASP.NET postback)
python scripts/ma/infoservices_download.py     # doe.mass.edu/infoservices bulk Excel archive
```
`MA_MIN_YEAR` environment variable controls the earliest year pulled (default: 2019):
```bash
MA_MIN_YEAR=2015 python scripts/ma/download.py
```

### New York
```bash
python scripts/ny/download.py   # data.nysed.gov Report Card DB (MS Access per year)
```

### Georgia
```bash
python scripts/ga/download.py           # GOSA repository per-year spreadsheets
python scripts/ga/insights_download.py  # GaDOE Insights Azure blob (405 files)
```

### Pennsylvania
```bash
python scripts/pa/download.py   # Future Ready PA data files + PDE reports
```

### Michigan
```bash
python scripts/mi/download.py        # mischooldata.org CDN static files + financial data
python scripts/mi/dashboard_scrape.py # legacy ASP.NET dashboard (enrollment, grad, M-STEP)
```

### Minnesota
```bash
python scripts/mn/mde_analytics_files.py    # MDE Analytics bulk files (the main source)
python scripts/mn/report_card.py            # Report Card API, all students
python scripts/mn/report_card_subgroups.py  # same reports by student group
```
`MN_TOPICS=1,545,87` limits the file-lister topics; `MN_YEAR`, `MN_LEVELS` and `MN_REPORTS` control the API scripts.

Minnesota's main source is MDE Analytics, and its 59 topics come in two flavours — the distinction is the whole trick:

- **File listers** (Assessment, Graduation, ACT, Student, Schools & Districts, North Star, Course Taking) look like dashboards but behave like a static index: set the dropdowns, press "List files", get direct download links. This is where the disaggregated statewide assessment data lives — 600 files spanning 1998-2025 (MCA, MTAS, Alt-MCA, MOD, GRAD, BST, ACCESS, TEAE, MTELL, SOLOM, WIDA) at state/county/district/school, each carrying Group Category and Student Group columns for race, gender, special education, English proficiency, economic status, homeless, migrant, military and SLIFE.
- **Report runners** (Discipline, School Finance/UFARS, Special Ed profiles) trip PerimeterX on "Run Report" and never generate. Backstopped by CRDC and Census F-33.

The Report Card API adds 16 report types at all three levels; note it returns all-students only, so `report_card_subgroups.py` re-requests each report per student group via the `categories=` parameter. Files here are large — single assessment files exceed 100 MB, and the Student Survey topic alone is 1,456 files, excluded from the default run.

### Missouri
```bash
python scripts/mo/mcds_download.py   # MCDS bulk files: MAP results by content area/grade and
                                     #   subgroup, enrollment to 1991, per-pupil expenditures,
                                     #   ASBR finance, faculty/certification, graduation, discipline
```
Not included: MCDS SSRS report-viewer reports (`SSRS_Print.aspx`) and Visualizations
dashboards. Re-checked during the coverage audit: `SSRS_Print.aspx?Reportid=...` serves
a District/LEA **parameter form**, not a report — and the wrapper ignores SSRS's
`rs:Format=EXCELOPENXML|EXCEL|CSV` export parameters (all return the same HTML). They
are per-district viewers over data the statewide bulk files already contain.

**Missouri publishes almost no gender breakdowns** — only 3 of 252 files contain a
gender dimension (vs 96 with race), confirmed by reading file contents. Race, ELL,
IEP/504 and FRL are well covered. Gender-disaggregated MO data would need CRDC.

A coverage audit (570 pages across dese.mo.gov + MCDS + school-finance) found **no
substantive new datasets**: of 131 new candidates only 45 were spreadsheets, and those
are MOSIS submission templates, file-layout "translation guides", and planning
calculators (grant tracking, formula projection, weather make-up) — field specs, not
records. They are kept under `data/raw/mo/audit_new/` but the MCDS bulk pull is
Missouri's complete public dataset.

### Indiana
```bash
python scripts/in/download.py        # IDOE Data Center bulk files (in.gov/doe/files): crawls the
                                     #   data center + archive pages for .xlsx/.pdf links. Assessment
                                     #   (ILEARN 3-8 + Biology incl. disaggregated, IREAD, I AM, SAT,
                                     #   ACT, ECA), enrollment/demographics (grade/ethnicity/FRL/
                                     #   gender/SpEd/ELL to 2006), attendance, graduation (state/
                                     #   federal, AP, IB), federal accountability, teacher statistics
```
Discipline is not published on the IDOE Data Center; it's covered for Indiana by CRDC.

```bash
python scripts/common/fetch_candidates.py data/raw/in/audit_candidates.csv --out data/raw/in/audit_new
```
A later coverage audit recovered **96 more files (157 MB)** the original `/doe/it/`
crawl missed, because they live outside the Data Center: **DLGF district finance**
(certified budgets, levies and tax rates by district/fund, 2022-2026 — on
`in.gov/dlgf`, a *different agency site*), **College Readiness/Going cohort datasets
2017-2024** (race/gender/IEP/ELL/FRL), and **Public Special Education Data SY2020-24**.
30 of the 96 carry verified demographic breakdowns.

**Indiana finance is dashboard-only.** Form 9 (revenue/expenditure/cash balances per
corporation and charter) is published solely as an embedded Power BI report in EdData;
`in.gov/doe/school-operations/finance/` carries just one bulk file (CY-2021 AFR).
`scripts/in/eddata_dashboards.py` implements the capture but **does not currently
work**: unlike Arizona's `app.powerbi.com` embeds, EdData uses the Power BI
**Government cloud** (`app.powerbigov.us`, querydata on `analysis.usgovcloudapi.net`).
The embed only renders inside the wrapper page (loading the iframe URL directly yields
a spinner), and under Playwright — headless *and* headed — the visuals never paint, so
only the report's `modelsAndExploration` metadata is returned and no `querydata` fires.
Indiana district finance is therefore covered by **Census F-33**.

### Kansas
```bash
python scripts/ks/assessment.py           # KAP test scores — 11 annual full workbooks
                                          #   (state + district + BUILDING level) plus the
                                          #   counts supplement. NOT in Data Central.
python scripts/ks/normalize_assessment.py # -> assessment_all_years.csv (2.21M rows)
python scripts/ks/download.py          # KSDE Data Central: 19 reports x state/district/county x
                                       #   years, most already broken out by race/ethnicity
```
KSDE splits its data across two systems, which is easy to miss:

- **Data Central** (`download.py`) holds attendance, graduation, enrollment, discipline, staff and directory — but **no test scores**. There is no JSON API; the page is ASP.NET WebForms and the final submit returns `application/vnd.ms-excel` directly, so the generator *is* the download endpoint. `KS_YEARS=2019-2025` and `KS_REPORTS=13,7` narrow the run; the default spans 2002-2025 because several reports are historical-only.
- **Building Report Card** (`assessment.py`) holds the assessment data, in two forms:
  - **Annual full workbooks** — `<YYYY>_<YYYY+1>_Assessment_Full_File.xlsx`, linked from the page as "Download Full Results". These are the complete dataset: state, district **and building** level, every grade, subject and student subgroup, ~300k rows each. 2014-15 to 2024-25 are published (193 MB total).
  - **`dataService.svc/getPerfChart2016`** — plain JSON, no session or token, `progYear=0` returns a five-year series in one call. Worth pulling as a supplement because it carries **counts** (total tested, students per level) that the workbooks omit — those are percentages only. `KS_ASSESS_FULL` / `KS_ASSESS_API` toggle each half.

  Two traps before you use the workbooks. **Each file is a two-year window** —
  `2023_2024` holds sheets `2023` *and* `2024`, `2024_2025` holds `2024` and `2025` — so
  every year but the endpoints appears twice, and the copies differ because KSDE revises.
  And KSDE reshaped the layout roughly every other year: six schemas across the eleven
  files, headers renamed, columns reordered, the all-grades aggregate spelled
  `All Grades`, `ALL` or the bare code `13`.

  `normalize_assessment.py` handles both — it maps every layout onto one schema, then
  dedupes on (year, org, building, group, grade, subject, population) with the later
  workbook winning, keeping rows an earlier edition has that the later one dropped.
  Output `assessment_all_years.csv`: **2,209,296 rows** (from 3,167,169 read — 957,873
  were window duplicates), 2015-2025 with 2020 absent for COVID. Entity codes are `0`
  for the state, `D####` for districts and `Z####` for the two Catholic dioceses. One more caveat:
  2015-16 and 2016-17 carry a `Population` column with both "Accountability" and
  "Report Card" rows — filter on it or those two years still double-count.

Both hosts serve an incomplete TLS chain, so certificate verification is disabled for them (public data, no credentials sent). Kansas publishes 32 student groups across the assessment workbooks — race, free/reduced lunch, disability, EL, gifted, migrant, mobility, homeless, military, foster care — but **gender only in 2014-15 and 2017-18**; the other eight years omit it, as does the `getPerfChart2016` service (20 groups, no gender). Outside assessment, gender appears in the graduation report.

### Mississippi / New Mexico / Idaho
```bash
python scripts/ms/download.py          # mdek12.org/publicreporting — per-year (2018-19..2025-26)
                                       #   + Assessment/Accountability/Reports/Diplomas/Staff pages
python scripts/nm/download.py          # web.ped.nm.gov — achievement by year (ELA/Math/Science
                                       #   proficiency, incl. by-assessment and by-subtest/grade),
                                       #   graduation cohorts 4/5/6-yr, schools directory
python scripts/id/download.py          # sde.idaho.gov finance-transparency — ADA/support units,
                                       #   enrollment by building/district/grade, revenues &
                                       #   expenditures, financial summaries, staff salary reports
python scripts/id/reportcard.py        # idahoreportcard.org export API: 38 measures x 6 years at
                                       #   state+district+school x 29 student groups (192 files,
                                       #   5.7M rows)
```
The Report Card is a Blazor app, but its export is a plain unauthenticated JSON endpoint (`POST /api/DataExport/csv`); the numeric measure/breakdown ids were recovered by probing it and reading the `Measure Label`/`Student Group` columns back. That yields **38 measures vs the 18 the UI lists**, and exposes Male/Female, which the UI buries in a nested picker. Oversized selections are refused, so the breakdown list is split in half recursively per measure-year.
All three share the crawl engine in `scripts/common/static_site.py` (seeds + a follow regex). Note Mississippi rejects file requests that arrive without a same-site `Referer`; the engine retries with one.

### Federal Datasets
```bash
python scripts/crdc/download.py       # CRDC national files → per-state discipline CSVs
python scripts/census_f33/download.py # Census F-33 district finance → per-state CSVs
```

## Output and Manifests

Every script writes a `manifest.csv` alongside its downloaded files:

```
data/raw/<state>/manifest.csv
data/raw/<state>/infoservices/manifest.csv   # where sub-sources exist
```

Manifest columns (varies by script):
```
state, source, category, entity_level, entity_id, entity_name,
year, file_url, local_path, status, size_bytes, sha256
```

All scripts skip files that already exist locally (`status = skipped_existing`), so reruns are safe and incremental.

## Collection Methods

### 1. Static file crawl
Parse an index page for `.xlsx/.csv/.zip/.pdf` links, download each. Used by UT, NY, PA, GA (GOSA), MA infoservices, and parts of every other state.

### 2. REST API
Call structured JSON endpoints with year/entity parameters. Used for AZ and FL report cards, NV assessment data. Fastest and cleanest method — preserves structured data without parsing HTML.

### 3. ASP.NET form replication
For legacy .NET sites that render data as an HTML table after a form POST. Extract hidden fields (`__VIEWSTATE`, `__EVENTVALIDATION`), POST with the desired year/level, parse the returned table. No browser needed. Used for MA profiles.doe.mass.edu.

### 4. Headless browser (Playwright)
For JavaScript-rendered pages. Playwright loads the page as a real browser, waits for rendering, then extracts content or captures network responses. Used for CA (captcha bypass), MI dashboard (iframe + tab-separated text extraction), NV doe.nv.gov, AZ finance dynamic portal.

### 5. Captcha / bot-protection bypass
California's CDE site uses Radware bot detection. Bypass: configure Playwright to mask `navigator.webdriver`, set a realistic User-Agent/viewport/timezone/locale matching a real Mac/Chrome session, and add gentle pacing between requests. The actual file downloads (on a CDN subdomain) have no protection.

### 6. Hidden endpoint discovery
Georgia's DOE Insights is a Power BI dashboard backed by Azure blob storage. Method: open browser DevTools → Network tab → interact with the dashboard → capture the blob storage URL from AJAX traffic. The blob turned out to be publicly accessible, so all 405 files were downloaded directly.

### 7. Federal dataset substitution
When state sources are blocked (Florida finance: Akamai WAF; MI/NV interactive dashboards: JS-gated), federal datasets fill the gap: CRDC (discipline, enrollment, staff) and Census F-33 (district finance) cover all 50 states and are freely downloadable.

### 8. Socrata catalog API
City/state open-data portals built on Socrata (DataSF, Oakland Open Data, Utah Open Data) expose a catalog search API (`/api/catalog/v1`) to discover dataset IDs and a direct CSV export per dataset (`/resource/<id>.csv`) — no scraping needed. Used for `scripts/ca/local_portals_download.py` and `scripts/ut/opendata_download.py`. Some catalog entries are Socrata "story" assets (narrative dashboard pages) rather than downloadable tables and must be filtered out.

### 9. Embedded BI dashboard extraction (Tableau / Power BI)
Some data is published *only* inside an interactive BI dashboard, with no file download. Two patterns crack these:

- **Tableau embed → Embedding API v3.** The USBE Data Gateway serves a Tableau Cloud view via a `<tableau-viz>` web component authenticated by a Connected-App JWT the page mints. We can't call the Tableau server directly, but loading the public page authenticates the embed, after which we read the underlying worksheets in-page via the official `getSummaryDataAsync()` API and drive filters with `applyFilterAsync()`. Used for `scripts/ut/datagateway_proficiency.py` (proficiency by gender/race/etc., which the static reports omit).
- **Power BI "view" embed → querydata capture.** ADE's Workforce dashboards are Power BI embeds. Each visual POSTs to `<region>.analysis.windows.net/public/reports/querydata` and gets back a compressed "DSR" result. We load the embed, nudge it so every visual issues its query, capture each response, and decode the DSR (schema + `C`/`R`/`Ø` bitmask rows, `ValueDicts`, and nested `X`/`SH` trend matrices) into tidy CSVs. Used for `scripts/az/workforce_dashboards.py` (teacher demographics + 2019-2026 trends).

## Data-Discovery Tooling (local LLM + content verification)

Three helpers used to audit coverage after a state is scraped. The LLM runs locally
via Ollama (`ollama serve`, default model `qwen2.5:14b` — set `LLM_MODEL` to change);
nothing leaves the machine and results are cached under `data/cache/llm/`.

```bash
python scripts/common/reclassify_manifest.py data/raw/mo/mcds/manifest.csv   # -> manifest_llm.csv
python scripts/common/verify_dims.py         data/raw/mo/mcds/manifest_llm.csv # -> manifest_verified.csv
python scripts/common/site_audit.py --state in --no-rank --depth 2 \
    --seeds <urls...> --manifest data/raw/in/manifest.csv --out data/raw/in/audit_candidates.csv
```

- **`llm_assist.py`** — batched file-label classification (category + demographic
  dimensions) and page-link ranking. Keyword rules filed 54% of Missouri's files as
  "other"; the model cut that to 4%.
- **`verify_dims.py`** — **the authoritative check.** The LLM guesses dimensions from
  a file's *title*, which over- and (more often) under-claims. This opens each
  downloaded file and detects race / gender / IEP-504 / ELL / FRL from actual headers
  and values, handling both wide (one column per subgroup) and long ("Student Group"
  column) layouts. Measured against file contents, title-guessing missed 154 Indiana
  and 43 Missouri files that really do carry breakdowns — always filter on
  `verified_dims`, not `llm_dims`.
- **`site_audit.py`** — crawls seed pages (keyword prefilter, optional LLM ranking),
  diffs found files against existing manifests, and reports only new candidates.
  Use `--no-rank` on link-heavy sites; LLM-ranking every link costs more than it adds.
- **`fetch_candidates.py`** — downloads audit results (tabular formats by default; a
  DOE sweep surfaces far more PDF guidance than data — Indiana's was 683 PDFs vs 97
  data files).

**Caveat on `verify_dims.py`:** it detects demographic *columns*, which also match
blank submission templates and file-layout specs (Missouri's MOSIS batch files define
`Gender: 0 = female, 1 = male` but hold no records). It answers "does this file have
demographic fields", not "does this file contain data". Check row counts too.

Verified demographic coverage, read from file contents rather than filenames
(states scraped as API/JSONL rather than files are not listed):

| State | files w/ demographics | race | gender | IEP/504 | ELL | FRL |
|---|---|---|---|---|---|---|
| Minnesota | 487 / 788 | 420 | 197 | 325 | 345 | 209 |
| Kansas | 501 / 627 | 393 | 281 | 409 | 242 | 303 |
| New Mexico | 195 / 233 | 160 | 148 | 124 | 190 | 151 |
| Indiana | 296 / 330 | 296 | 111 | 223 | 129 | 141 |
| Missouri | 115 / 252 | 100 | **3** | 70 | 100 | 38 |
| Idaho | 80 / 291 | 51 | **1** | 52 | 20 | 0 |
| Mississippi | 35 / 178 | 26 | 8 | 24 | 14 | 8 |

Missouri's gender count is not a bug — it publishes almost no gender breakdowns.
Kansas is nearly the same story for assessment: of its 32 student groups only
2014-15 and 2017-18 break out Males/Females — the other eight years cover race,
poverty, disability, EL and mobility but not gender, which is otherwise in graduation.
Idaho's and Mississippi's totals are held down by PDFs, which carry no readable
columns; Idaho's Report Card API data covers that gap separately.

## Known Limitations and Gaps

See `docs/coverage_matrix.md` for full detail. Key remaining gaps:

- **Florida finance (FEFP)** — `fldoe.org` returns 403 from Akamai even with a stealth browser. Filled by Census F-33 for finance.
- **Michigan ISD/district dashboard breakdowns** — the `Common_Locations` parameter format for sub-state entities was not reverse-engineered. District/school data comes from the static CDN files.
- **Nevada non-assessment interactive data** — the NV report card builder resists programmatic interaction. Additional categories covered via doe.nv.gov static pages and CRDC.
- **Massachusetts PowerBI accountability dashboard** — reviewed, not yet scraped (would use the Power BI querydata-capture approach now proven for AZ workforce).
- **Utah gender in assessments** — *(resolved)* the static reports break out race/disability/ELL but not gender; gender proficiency now comes from the Data Gateway Tableau view (state-level, `scripts/ut/datagateway_proficiency.py`). LEA/school-level gender is not published anywhere.
- **Arizona bulk teacher/staff records** — ADE publishes no downloadable staff file (SDER is PDFs; OACIS is per-educator lookup). School-level staff by race/sex/experience comes from CRDC; state/county teacher demographics + trends come from the Power BI Workforce dashboards (`scripts/az/workforce_dashboards.py`).

## Scaling to 50 States

The recon → classify → script workflow is the same for every new state:

1. Visit the state DOE website, find the "Data & Reports" or "Downloads" section
2. Classify: static files / REST API / dashboard?
3. Adapt the closest existing script (most states are Method 1 or 2)
4. **Check the five categories against what you actually collected**, not against
   what the portal seemed to offer
5. Check CRDC and Census F-33 as fallbacks for blocked or missing categories
6. Document sources and gaps in `docs/coverage_matrix.md`

Step 4 exists because the same mistake cost real data three times: assuming one
portal is the whole agency.

| State | What was missed | Where it actually was |
|---|---|---|
| Minnesota | 828 files / 5.2 GB of disaggregated assessment | A "file lister" page that looked like a blocked dashboard until someone pressed *List files* in a real browser |
| Indiana | District finance, college-readiness cohorts, SpEd child counts | `in.gov/dlgf` — a **different agency**, plus `/doe/school-operations/` outside the data centre |
| Kansas | All assessment data | `ksreportcard.ksde.gov`, a second KSDE system; Data Central has none |

Cheap checks that would have caught all three: press every submit button in a real
browser before concluding a portal is empty, crawl sibling agency domains, and
count categories per state after collection — a state with zero assessment files
is a red flag, not a fact.

A config-driven structure for 50-state scale would consolidate shared logic into `scripts/common/` and drive each state from a `config/states.yaml` file specifying URLs, file types, and method.
