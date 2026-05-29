# UMich Ross EOQ Education Data Pipeline

This project collects publicly available education data from the Arizona Department of Education and the Florida Department of Education. The goal is to automate downloading public files and reports related to assessments, enrollment, graduation, dropout rates, school finance, staff/teacher records, discipline, and other public education datasets.

The project is designed to be reproducible, so the same approach can later be expanded to all 50 states and rerun each year.

## Assigned States

* Arizona
* Florida

## Project Goals

The first task was to download as many publicly available education files as possible from the assigned states within the time available.

Target data categories include:

* Test scores and assessments
* ELA, Math, Science, ACT, SAT, AP where available
* Financial reports
* Budget reports
* Audit reports
* Teacher and staff records
* Enrollment data
* Graduation and dropout data
* Discipline and suspension data
* School, district, and state-level report card data

## Repository Structure

```text
umich-ross-eoq/
  requirements.txt
  README.md
  scripts/
    az/
      accountability_research.py
      finance_static_download.py
      finance_dynamic_download.py
      report_cards_reports.py
    fl/
      scrape.py
```

Downloaded data is saved locally under a `data/` folder when the scripts are run. The raw data folder is intentionally not stored in GitHub because downloaded public datasets can be large.

Expected local output structure:

```text
data/
  raw/
    az/
      accountability_research/
      finance/
      finance_dynamic/
      reportcards/
    fl/
      fldoe/
```

## Setup

This project works best with Python 3.12.

### 1. Clone the repository

```bash
git clone https://github.com/vtirum/umich-ross-eoq.git
cd umich-ross-eoq
```

### 2. Create a virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

If `python3.12` is not installed on Mac, install it with Homebrew:

```bash
brew install python@3.12
```

### 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Install Playwright browser support

```bash
playwright install chromium
```

On Linux, this may be needed instead:

```bash
playwright install --with-deps chromium
```

## Scripts

### Arizona Accountability and Research

```bash
python scripts/az/accountability_research.py
```

This script targets public Arizona accountability files such as:

* Assessment data
* ELA and Math files
* Science files
* EL assessment files
* Graduation data
* Dropout data
* Enrollment data
* Public Excel, PDF, ZIP, and PowerPoint files linked from the Arizona Accountability and Research page

### Arizona Report Cards

```bash
python scripts/az/report_cards_reports.py
```

This script targets the Arizona Report Cards API. It collects data by fiscal year and entity.

The script pulls:

* Fiscal years
* School and district entity lists
* State-level report data
* School-level report data
* District-level report data

Example report categories include:

* Student Enrollment
* Teacher Qualification
* Assessment Proficiency Level
* Assessment Participation Rates
* Graduation Rate
* Dropout Rate Trends
* Enrollment Trends
* Chronic Absenteeism
* English Learner data

The report card data is pulled from the public API instead of scraping the rendered HTML.

### Arizona Finance Static Files

```bash
python scripts/az/finance_static_download.py
```

This script downloads static public finance files from Arizona finance pages.

Target categories include:

* SAFR digital data
* Superintendent Annual Reports
* Audit reports
* Budget-related documents
* Fundable LEA lists
* Financial reporting files

### Arizona Finance Dynamic Capture

```bash
python scripts/az/finance_dynamic_download.py
```

Some Arizona finance reports are located in dynamic report portals rather than direct file links. This script uses Playwright to open those pages and capture downloadable files or API responses after the page loads.

This is useful for pages where reports require selecting fiscal year, LEA, or report type.

### Florida Department of Education

```bash
python scripts/fl/scrape.py
```

This script downloads public static files from Florida Department of Education pages.

Target categories include:

* PK-12 public school data reports
* Student reports
* Staff and teacher reports
* School reports
* Florida Data reports
* Archive reports
* Assessment files
* Discipline data
* Finance-related files where linked

## Data Sources

### Arizona

Main public sources used:

* Arizona Department of Education Accountability and Research data pages
* Arizona public data pages
* Arizona school finance pages
* Arizona Report Cards public API
* Arizona finance report and budget pages

### Florida

Main public sources used:

* Florida Department of Education Data Systems
* PK-12 Public School Data Publications and Reports
* Students reports
* Staff reports
* School reports
* Florida Data reports
* Archives
* Assessment results pages
* School grades and accountability pages
* Discipline data pages
* Finance pages

## Output and Manifests

The scripts are designed to save downloaded files locally and produce metadata where applicable.

Typical metadata fields include:

```text
source_page
link_text
file_url
category
local_path
status
size_bytes
sha256
fiscal_year
entity_id
entity_name
entity_kind
report
```

The manifest files are important because they document:

* Where each file came from
* What page linked to it
* Whether the download succeeded
* Where it was saved locally
* File size and hash when available
* Which state, year, entity, or report the data belongs to

## Methodology

The project uses three collection methods:

### 1. Static Link Scraping

For normal public pages, the scripts parse the HTML, collect links to files, filter by file type, and download matching files.

Common file types:

```text
.xlsx
.xls
.csv
.pdf
.zip
.doc
.docx
.ppt
.pptx
```

### 2. Browser Automation with Playwright

Some pages use JavaScript or require a real browser session before data appears. For those pages, Playwright is used to load the page, wait for JavaScript, inspect links, and capture downloads or network responses.

### 3. Direct API Collection

For Arizona Report Cards, the useful data is exposed through public API endpoints. The project calls those endpoints directly and saves the JSON responses.

This is better than scraping the rendered webpage because it preserves structured data.

## Limitations

This project collects the majority of obvious public and downloadable education files from the main Arizona and Florida education data pages, but it does not guarantee complete coverage of every public education record.

Potential missing data includes:

* Interactive dashboard exports that require manual filter selection
* Data hidden behind dynamic portals
* Files only available by request
* Restricted reports requiring school, district, or agency login
* Older archived files not linked from current pages
* Reports blocked by server protections or unavailable during collection

For Florida, some interactive tools such as Know Your Data and Know Your Schools may require separate Playwright or API extraction.

For Arizona, some school finance portals may require separate endpoint discovery or manual report selection.

## How to Rerun the Pipeline

Activate the virtual environment:

```bash
source .venv/bin/activate
```

Run Arizona scripts:

```bash
python scripts/az/accountability_research.py
python scripts/az/report_cards_reports.py
python scripts/az/finance_static_download.py
python scripts/az/finance_dynamic_download.py
```

Run Florida script:

```bash
python scripts/fl/scrape.py
```

## Recommended Workflow

For a clean full run:

```bash
rm -rf data/raw
mkdir -p data/raw

python scripts/az/accountability_research.py
python scripts/az/report_cards_reports.py
python scripts/az/finance_static_download.py
python scripts/fl/scrape.py
```

Then review the generated manifests and failed download logs.

## Scaling to 50 States

To scale this project to all 50 states every year, the recommended approach is to make the scraper configuration-driven.

Instead of writing completely separate logic for every state, each state should have:

```text
state name
source URLs
allowed domains
target file types
category keywords
dynamic/API notes
```

A future structure could look like:

```text
config/
  states.yaml
scripts/
  common/
    downloader.py
    manifest.py
    file_utils.py
    playwright_capture.py
  az/
  fl/
  ca/
  tx/
```

Each yearly run should save data under a year-specific folder:

```text
data/raw/2026/AZ/
data/raw/2026/FL/
metadata/2026/files_manifest.csv
```

The most important field for yearly reruns is the file hash, such as `sha256`, because it allows the pipeline to identify files that have not changed.

## Notes for Sharing Data

The GitHub repository contains code, but not necessarily all downloaded raw data. Raw public data files can be large, so they should be shared separately through:

* Google Drive
* Box
* OneDrive
* S3
* University storage

When sharing the final output, include:

```text
code/
data/raw/
metadata/manifests/
docs/source_notes.md
README.md
requirements.txt
```

## Current Status

The repository contains working scripts for collecting public education data from Arizona and Florida. The Arizona scripts cover accountability data, report card API data, and finance data. The Florida script covers static FLDOE public data files and can be expanded to handle additional interactive portals.

The project is a strong first pass for collecting the majority of publicly downloadable education data for Arizona and Florida.
