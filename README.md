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
```

### Florida
```bash
python scripts/fl/scrape.py            # static FLDOE data pages
python scripts/fl/report_cards.py     # FL report cards API
python scripts/fl/edudata_export.py   # Tableau/edudata API
```

### California
```bash
python scripts/ca/download.py               # bulk CDE data files (assessment, enrollment, staff, finance, school directory)
python scripts/ca/assessment_download.py    # CAASPP/ELPAC statewide assessment research files
python scripts/ca/local_portals_download.py # DataSF + Oakland Open Data (Tier-L local portals)
```

### Utah
```bash
python scripts/ut/download.py             # USBE reports page bulk Excel/PDF downloads
python scripts/ut/opendata_download.py    # Utah Open Data (opendata.utah.gov) USBE-owned datasets
```

### Nevada
```bash
python scripts/nv/download.py            # NV Report Card API (SBAC + ACT assessment, All Students)
python scripts/nv/subgroups_download.py  # SBAC + ACT by race/ethnicity, gender, IEP, EL, FRL
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

## Known Limitations and Gaps

See `docs/coverage_matrix.md` for full detail. Key remaining gaps:

- **Florida finance (FEFP)** — `fldoe.org` returns 403 from Akamai even with a stealth browser. Filled by Census F-33 for finance.
- **Michigan ISD/district dashboard breakdowns** — the `Common_Locations` parameter format for sub-state entities was not reverse-engineered. District/school data comes from the static CDN files.
- **Nevada non-assessment interactive data** — the NV report card builder resists programmatic interaction. Additional categories covered via doe.nv.gov static pages and CRDC.
- **Massachusetts PowerBI accountability dashboard** — reviewed, not yet scraped (would require network-capture approach similar to GA Insights).

## Scaling to 50 States

The recon → classify → script workflow is the same for every new state:

1. Visit the state DOE website, find the "Data & Reports" or "Downloads" section
2. Classify: static files / REST API / dashboard?
3. Adapt the closest existing script (most states are Method 1 or 2)
4. Check CRDC and Census F-33 as fallbacks for blocked or missing categories
5. Document sources and gaps in `docs/coverage_matrix.md`

A config-driven structure for 50-state scale would consolidate shared logic into `scripts/common/` and drive each state from a `config/states.yaml` file specifying URLs, file types, and method.
