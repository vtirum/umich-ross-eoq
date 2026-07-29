# UMich Ross EOQ Education Data Pipeline

Automated collection of publicly available K-12 education data across 10 states. Covers assessments, enrollment, finance, teacher/staff records, and discipline/suspension data at the state, district, and school level. Designed to be reproducible and extensible to all 50 states.

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
| **Minnesota** | rc.education.mn.gov (Minnesota Report Card, WebFOCUS JSON API) | API |
| **Missouri** | apps.dese.mo.gov/MCDS (Missouri Comprehensive Data System bulk files) | Static |
| **Indiana** | in.gov/doe/it/data-center-and-reports (IDOE Data Center bulk files) | Static |

**Federal supplements (all states):**
- `scripts/crdc/` — CRDC discipline, enrollment, and staff (covers all 10 states)
- `scripts/census_f33/` — Census F-33 district finance survey (fills gaps where state finance sources are blocked)

## Data Categories

All five categories are covered for all 10 states:

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
    az/                      # Arizona
    ca/                      # California
    census_f33/              # Federal Census F-33 finance (all states)
    crdc/                    # Federal CRDC discipline/enrollment/staff (all states)
    fl/                      # Florida
    ga/                      # Georgia
    ma/                      # Massachusetts
    mi/                      # Michigan
    nv/                      # Nevada
    ny/                      # New York
    pa/                      # Pennsylvania
    ut/                      # Utah
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
python scripts/az/accountability_research.py   # static accountability + assessment files
python scripts/az/report_cards_reports.py      # report cards API (all entities × years)
python scripts/az/finance_static_download.py   # static finance files
python scripts/az/finance_dynamic_download.py  # dynamic finance portal (Playwright)
python scripts/az/workforce_dashboards.py      # ADE Workforce (Power BI) teacher demographics:
                                               #   race, gender, education, experience, content area,
                                               #   grade band, county + 2019-2026 trends (TIA-sourced)
```

### Florida
```bash
python scripts/fl/scrape.py            # static FLDOE data pages
python scripts/fl/report_cards.py      # FL report cards API (includes GetTGELA: assessment by gender/race/IEP/ELL)
python scripts/fl/edudata_export.py    # Tableau/edudata API
python scripts/fl/fldoe_download.py    # fldoe.org bulk files via Wayback Machine proxy (bypasses Akamai WAF):
                                       #   attendance, enrollment, staff, graduation, 2025 FAST assessments
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
python scripts/ut/datagateway_proficiency.py  # USBE Data Gateway (Tableau) RISE/UA Plus/DLM proficiency
                                              #   BY DEMOGRAPHIC GROUP incl. gender (the static reports
                                              #   omit gender); state-level, all years, via Tableau API
```

### Nevada
```bash
python scripts/nv/download.py            # NV Report Card API — 6 assessments (All Students):
                                         #   SBAC ELA/Math 3-8, CCR Grade 11, Science 5/8,
                                         #   Science 9/10, NAA (alternate), ELPA
python scripts/nv/subgroups_download.py  # same 6 assessments by race/ethnicity, gender, IEP, EL, FRL
python scripts/nv/reportcard_full.py     # extended NV report card categories
python scripts/nv/doe_download.py        # doe.nv.gov topic pages (enrollment, finance, staff, CTE)
```

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
python scripts/mn/report_card.py     # Minnesota Report Card WebFOCUS API — 16 report types at
                                     #   state + district + school level: assessment (North Star
                                     #   achievement/progress, MN Growth, NAEP), demographics,
                                     #   graduation, staffing, fiscal transparency, college-going,
                                     #   English learners, early childhood, HS courses, well-rounded
```
```bash
python scripts/mn/report_card_subgroups.py  # same reports BY DEMOGRAPHIC SUBGROUP —
                                             #   race (8 ethnicity groups), IEP (special ed),
                                             #   ELL, FRP, + gender (graduation/participation/
                                             #   college). Uses the Report Card `categories=`
                                             #   param; report_card.py alone is all-students only.
```
Environment overrides: `MN_YEAR` (default 2024, trends embedded), `MN_LEVELS=state,district,school`, `MN_REPORTS=graduation,demographics,...` (all-students script); `MN_SUB_LEVELS=state,district` (subgroup script — school-level is possible but ~250k requests and mostly privacy-suppressed). Discipline (suspensions/expulsions/violence/referrals) and detailed MCA-by-test/subject/grade are form-driven endpoints not yet wired; discipline is covered for MN by CRDC.

### Minnesota — MDE Analytics bulk files
```bash
python scripts/mn/mde_analytics_files.py   # pub.education.mn.gov/MDEAnalytics file-listing topics
```
The MDE Analytics portal has ~59 topics in **two flavors**, and the distinction matters:

- **File-listing topics** (Assessment Files, Graduation, ACT, Student, Schools & Districts, North Star, Course Taking, Student Survey) — dropdown filters + a "List files" button that returns a table of bulk files. The files are served from `education.mn.gov/mdeprod/idcplg?IdcService=GET_FILE&dDocName=<ID>`, a host with **no bot protection**, so they download with plain requests. **This is where MN's disaggregated statewide assessment data lives**: 602 files, 1998-2025 (MCA, MTAS, Alt-MCA, MOD, GRAD, BST, ACCESS/Alternate ACCESS, TEAE, MTELL, SOLOM, WIDA) at state/county/district/school level, broken out by student group (race/ethnicity, gender, special education, English learner, FRP) subject to small-N suppression. The script replicates the listing POST (`IBIF_ex=mdea_ddl_file_listing`, `COMBO1-5=FOC_NONE`, plus a per-session `IBIWF_SES_AUTH_TOKEN` scraped from the driver page).
- **Report-runner topics** (Discipline Data, the School Finance/UFARS sections, Special Ed profiles) — interactive WebFOCUS reports whose "Run Report" trips **PerimeterX (HUMAN)** bot detection (`js_zpsbd3` beacon) from an automated browser. Not scraped; backstopped by CRDC (discipline) and Census F-33 (finance).

`MN_TOPICS=1,545,87` restricts to specific TOPICIDs. Note the files are large (single assessment files run 100 MB+); the Student Survey topic alone is 1,456 files and is excluded from the default core run.

### Missouri
```bash
python scripts/mo/mcds_download.py   # MCDS bulk files (apps.dese.mo.gov/MCDS): browser harvests
                                     #   the JS-rendered file links per category, requests downloads
                                     #   each. Assessment (MAP by content area/grade + subgroup,
                                     #   score distributions), enrollment/demographics (to 1991),
                                     #   finance (per-pupil expenditures, ASBR), staff (faculty,
                                     #   certification, ratios), graduation/dropout, discipline
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

Verified demographic coverage (from file contents, not filenames):

| State | files w/ demographics | race | IEP/504 | ELL | FRL | gender |
|---|---|---|---|---|---|---|
| Indiana | 296 / 330 | 296 | 223 | 129 | 141 | 111 |
| Missouri | 109 / 252 | 96 | 68 | 94 | 37 | **3** |

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
4. Check CRDC and Census F-33 as fallbacks for blocked or missing categories
5. Document sources and gaps in `docs/coverage_matrix.md`

A config-driven structure for 50-state scale would consolidate shared logic into `scripts/common/` and drive each state from a `config/states.yaml` file specifying URLs, file types, and method.
