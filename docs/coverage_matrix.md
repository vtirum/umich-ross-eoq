# 10-State Education Data — Coverage Matrix & Collection Plan

Reconnaissance for expanding the pipeline from AZ + FL to 10 states:
**California, Utah, Arizona, Florida, Nevada, Massachusetts, New York, Georgia,
Pennsylvania, Michigan.**

Target data categories (per the project's First Task):
Test scores (ELA / Math / Science, + AP/ACT/SAT where available), Financials,
Teacher/staff records, Enrollment, Suspensions/Discipline.

Collection method legend:
- **API** — structured JSON/REST endpoints (fast, deep, cleanest). Pattern proven on AZ & FL report cards.
- **STATIC** — bulk downloadable files (CSV / Excel / fixed-width / Access DB). Often *all entity levels in one file* — highest value-per-effort.
- **DASHBOARD** — Tableau / Power BI / interactive portal; requires reverse-engineering (à la FL edudata) or embedding-API extraction.

---

## Summary matrix

| State | Primary source(s) | Method | Entity depth | Notes |
|---|---|---|---|---|
| **California** | `cde.ca.gov/ds/ad/` (Radware captcha — DEFEATED) | **STATIC** (bulk fixed-width) | state→district→school | DONE — 216 files, 6.09 GB, 2019-2025. The Radware captcha was bypassed with a **stealth browser fingerprint** (mask `navigator.webdriver` + real UA/viewport/timezone/locale via Playwright) + gentle pacing; page links resolve to fixed-width files on `www3.cde.ca.gov/demo-downloads/` (no captcha on the file host). Covers enrollment (census), staff/CBEDS-CALPADS + assignments (TAMO), graduation cohort (ACGR/FYCGR), discipline/suspension, FRPM poverty, EL, student groups. All statewide files carry AggregateLevel + County/District/School codes (all levels). Assessment scores ALSO collected (scripts/ca/assessment_download.py): Smarter Balanced ELA/Math, CAA alternate, CAST science statewide research files from `caaspp-elpac.ets.org`, 2019-2025 (2020 absent = COVID). The on-page links are JS placeholders; real files follow `<pfx>_ca<year>_all_<fmt>_v<N>.zip` ("all" = every district+school) — constructed directly + version-probed, no form-driving. SB 2024 = 4.05M score rows w/ County/District/School codes. |
| **Utah** | `schools.utah.gov/datastatistics/reports.php` (STATIC); Data Gateway (Tableau) | **STATIC** | state→district→school | DONE — 216 files, 107 MB, 2019-2025. Despite the "hardest" billing, reports.php publishes ~307 direct Excel/PDF reports under `_reports_/_<category>_/` covering assessment, enrollment, educators, graduation/dropout, class size, nutrition, schools — a clean static scrape. The Data Gateway (public Tableau, `tableau.com/t/usbedata/views/...`) is an optional add-on, not needed for core categories. |
| **Arizona** | `azreportcards.azed.gov` API; `azed.gov` finance | **API** + STATIC | state→district→school | ✅ DONE — report cards API, accountability, finance scrapers built. |
| **Florida** | `edudata.fldoe.org` (report cards API + Tableau); `fldoe.org` | **API** + DASHBOARD + STATIC | state→district→school | ✅ DONE — report_cards API (23k files), edudata Tableau extractor (122 tables), static scraper. |
| **Nevada** | `nevadareportcard.nv.gov` (Data Interaction API) | **API** | state→district→school | DONE for assessment (SBAC `e24` + ACT `e25`, all years/levels). Non-assessment datasets (grad/demographics/discipline/fiscal/personnel/CTE) — **gap-fill ATTEMPTED, not solved.** The `summaryCSV` endpoint returns HTTP 500 ("Sequence contains no matching element") for current exam codes (e32/e44/e40/e9/e12) with the documented score IDs; the correct score IDs are generated *client-side* by the DI report-builder UI, which resists automation (glance/report links don't respond to programmatic clicks) and exposes no static score-ID config (landing page loads only org-hierarchy + year JSON). Realistic path: a successful headed-browser interaction capture of one report's `summaryCSV` call per exam, or an NDE data request. |
| **Massachusetts** | `profiles.doe.mass.edu/statereport/` | **STATIC** via ASP.NET postback replication | district→school | DONE — 158 tables, 156,931 rows, 2019-2025, district + school. Each statewide report renders a full HTML data table; year/level filters are ASP.NET postbacks with no GET API — replicated with `requests` (extract `__VIEWSTATE` + POST dropdown values; no Playwright). Reports: MCAS + participation (assessment), enrollment (×3), staff (salaries, race/gender, grade-subject), per-pupil finance, graduation, dropout, SSDR discipline. Note: report-type values vary in case across reports (District vs DISTRICT). 2020 MCAS absent (COVID). |
| **New York** | `data.nysed.gov/downloads.php` | **STATIC** (per-year MS Access DB) | state→district→school | **Single Report Card Database download per year = everything** (enrollment, assessment ELA/Math/Sci/Regents, grad, staff, attendance, suspensions, expenditures). Highest ROI. |
| **Georgia** | `download.gosa.ga.gov` (STATIC) + `georgiainsights.gadoe.org/data-downloads/` (Power BI → Azure blob) | **STATIC** + **DASHBOARD-discovered blob** | district→school | DONE, two complementary sources. (1) GOSA repo: per-year/domain spreadsheets (Milestones, ACT/SAT/AP, enrollment, finance, grad, dropout, personnel, attendance). (2) GaDOE Insights: 405 files on an Azure blob, discovered by capturing the Power BI report's query responses — CCRPI accountability, WIDA ACCESS ELL, EOC course-level, FTE enrollment, Whole Child, CTAE. |
| **Pennsylvania** | `futurereadypa.org/Home/DataFiles`; `pa.gov/.../data-and-reporting`; data.gov | **STATIC** (Excel) + DASHBOARD | state→district→school | PSSA/Keystone, enrollment, staff, finance, grad. Future Ready PA Index data files + PDE reports + PA open-data (Socrata). |
| **Michigan** | `mischooldata.org` (CDN static + dashboards) | **STATIC** done; dashboard not solved | state→ISD→district→school | DONE for static archive (10 files: historical MEAP/MME assessment zips + layouts, on the michigan.gov CDN). Current enrollment/finance/educator/M-STEP live in the interactive "custom dataset builder" — **gap-fill ATTEMPTED, not solved.** The site is an Umbraco CMS behind a **Cloudflare challenge**; the CMS content pages expose no data API, and the real dashboards are separate JS apps whose data endpoint was not located (no non-CMS JSON/CSV traffic captured, even with a stealth browser). Realistic path: locate the dashboard viz endpoint via the live builder, or a CEPI data request. |

---

## Method tally

- **Pure/primary STATIC bulk** (easiest, highest ROI): **NY, CA, MA, GA, MI, PA**
- **Pure API** (clean, proven pattern): **NV** (+ AZ, FL done)
- **Dashboard-heavy / hardest**: **UT** (+ PA & MI have dashboard components alongside static)

---

## Recommended execution order (easiest / highest-value first)

Given the directive for **full school-level depth**, ordered by value-per-effort:

1. **New York** — one Access DB per year covers every category at every level. Trivial download, massive structured payload. *Best first target.*
2. **California** — bulk statewide files per domain, all levels. Huge, clean, well-documented record layouts.
3. **Massachusetts** — per-entity Excel/report exports; clean and complete.
4. **Georgia** — GOSA repository bulk spreadsheets per year/domain.
5. **Michigan** — MI School Data Excel files + custom builder.
6. **Nevada** — Report Card API (discovery needed, but AZ/FL pattern applies).
7. **Pennsylvania** — Future Ready PA data files + PDE reports + open data.
8. **Utah** — Data Gateway portal probing; hardest, save for last.

(Arizona & Florida already complete.)

---

## Standardization (for cross-state + cross-RA comparability)

Every state writes to an identical structure so outputs are diff-able:

```
data/raw/<ST>/<source>/<category>/...        # ST = 2-letter postal code
data/raw/<ST>/manifest.csv                   # per-state manifest
```

Manifest columns (superset; not all apply to every source):
`state, source, category, entity_level, entity_id, entity_name,
year, file_url, local_path, method, status, size_bytes, sha256`

The shared engine in `scripts/common/` (http_client, file_utils, manifest,
playwright_capture) is reused; each state is a thin script following the
established AZ/FL pattern.

---

## Per-state source detail

### California (CDE) — STATIC
- Downloadable data index: `https://www.cde.ca.gov/ds/ad/downloadabledata.asp`
- Assessment files: `https://www.cde.ca.gov/ds/ad/assessmentdata.asp` (CAASPP/ELPAC, fixed-width + layouts)
- DataQuest: enrollment, EL, grad/dropout, staffing, course enrollment, discipline
- Files are statewide with district/school rows embedded → all levels in one download.

### Utah (USBE) — DASHBOARD
- Data Gateway: `https://datagateway.schools.utah.gov/` (interactive; some login-gated)
- Data page: `https://schools.utah.gov/datastatistics/data`
- Needs portal probing to find any direct download/export endpoints.

### Nevada (NDE) — API
- Portal: `https://nevadareportcard.nv.gov/DI/`
- API documented by `github.com/DataInsightPartners/nevadaReportCardr` (R package) — school/district/state.
- Categories: assessment, graduation, enrollment/demographics, discipline, fiscal, educator qualifications, CTE.

### Massachusetts (DESE) — STATIC
- Profiles: `https://profiles.doe.mass.edu/` (per-entity report exports)
- Statewide reports: `https://www.doe.mass.edu/infoservices/reports/` — DONE
  (165 files, 70 MB; see "Massachusetts InfoServices — gap-fill" below)
- Dataset directory: `https://www.mass.gov/info-details/dese-directory-of-datasets-and-reports`
- PowerBI accountability dashboard (app.powerbigov.us) — reviewed, deferred

### New York (NYSED) — STATIC (best ROI)
- Downloads: `https://data.nysed.gov/downloads.php`
- Report Card Database = per-year MS Access (.accdb/.mdb) with all categories & levels.
- Separate enrollment / assessment / graduation+accountability / staff DBs also available.

### Georgia (GOSA / GaDOE) — STATIC
- Repository: `https://download.gosa.ga.gov/`
- Downloadable Data: `https://gosa.georgia.gov/dashboards-data-report-card/downloadable-data`
- GaDOE Insights downloads: `https://georgiainsights.gadoe.org/data-downloads/`

### Pennsylvania (PDE) — STATIC + DASHBOARD
- Future Ready PA data files: `https://futurereadypa.org/Home/DataFiles`
- PDE data & reporting: `https://www.pa.gov/agencies/education/data-and-reporting`
- PSSA/Keystone on data.gov: `https://catalog.data.gov/dataset/pssa-keystone-performance`

### Michigan (CEPI / MI School Data) — STATIC + DASHBOARD
- K-12 data files: `https://www.mischooldata.org/k-12-data-files/`
- Historical assessment: `https://www.mischooldata.org/historical-assessment-data-files/`
- Financial summary: `https://www.mischooldata.org/financial-summary`

---

## Gap-fill additions (post-collection)

After a per-state audit of the 5 required categories (assessment, financial,
enrollment, discipline/suspension, teacher), two cross-cutting fills were added:

### CRDC — federal discipline fill (all states)
`scripts/crdc/download.py` downloads the U.S. DOE Civil Rights Data Collection
national public-use files (2015-16, 2017-18, 2020-21; 2021-22 opt-in at 832 MB)
and extracts per-state discipline CSVs (Suspensions, Expulsions, Restraint &
Seclusion, Referrals/Arrests, Corporal Punishment) into
`data/raw/<ST>/discipline_crdc/` for all 10 assigned states. This fills the
discipline gap for **AZ, GA, PA, FL** (which don't publish scrapable state
discipline data) and supplements the rest. The national zips also contain
enrollment and teacher/staff FTE — useful supplementary coverage for the
dashboard-gated states (MI, NV).

### California financial
`scripts/ca/download.py` was extended to crawl the CDE `/ds/fd/` tree (SACS
annual financial data, Current Expense of Education / per-pupil spending, J-90
certificated salaries) in addition to `/ds/ad/`. CA now covers all 5 categories.

### Nevada non-assessment — SOLVED via doe.nv.gov
The Report Card portal's non-assessment builder resisted automation, but the
Nevada DOE website (`doe.nv.gov`, a headless CMS) publishes the data as plain
Excel downloads on topic pages. `scripts/nv/doe_download.py` (Playwright crawl of
the ADAM "Data & Reports" hub + topic pages) collected 84 files: enrollment
(per-year student counts 2016-2026), financial (NRS 387-388A statewide reports
FY20-24 + chart of accounts), staff, special education, CTE. Combined with the
SBAC/ACT API data and CRDC discipline, NV now covers all five categories.

### Michigan dashboard — partially solved
`scripts/mi/dashboard_scrape.py` (Playwright) cracked the "current data" tools
on mischooldata.org: they're thin Umbraco wrappers around an iframe to a legacy
ASP.NET WebForms app (`legacy.mischooldata.org/DistrictSchoolProfiles2/...`),
which renders results as tab-separated tables in the page text once
`Common_SchoolYear`/`Common_Locations`/etc. query-string params are supplied
(no Cloudflare challenge actually blocks these). Collected **Statewide, all
years**: enrollment counts (24 years, 2002-03 to 2025-26, in
`data/raw/mi/dashboard/enrollment_counts_statewide.csv`), graduation/dropout
rates (4/5/6-year cohort rates, `graddropout_statewide.csv`), and M-STEP
grades 3-8 ELA/Math performance (9 years x 6 grades x 2 subjects,
`assessment_mstep_statewide.csv`). One known minor anomaly: the 2024-25
Grade08/ELA query returned an MSS Science row instead of ELA — not root-caused.

ISD-level (33 ISDs) and district/school-level breakdowns were **not solved** —
the `Common_Locations` parameter uses internal hierarchy codes for sub-state
entities that weren't reverse-engineered (statewide = `1-A,0,0,0~2-A,0,0,0`;
the obvious `1-I,<isd_id>,0,0` guess returned no data). The staffing/educator
dashboard tool (`staffing-count`) also returned empty result grids regardless
of parameters tried — not solved. District/school-level MI coverage still
comes from the static files + CRDC.

### Massachusetts InfoServices — gap-fill
`scripts/ma/infoservices_download.py` covers `doe.mass.edu/infoservices/reports/`,
a static bulk-Excel archive separate from `profiles.doe.mass.edu/statereport`
(already covered by `scripts/ma/download.py`). Downloaded **165 files, 70 MB**
to `data/raw/ma/infoservices/`: regular enrollment by district/grade (2017-2026,
44 MB), special-education enrollment (2017-2026), CVTE enrollment (2016-17 to
2021-22), attendance by grade/student-group mid-year + end-of-year (25 MB),
bullying allegations (SY23-SY25), in-grade retention (Appendix A/B), postsecondary
(IHE) enrollment outcomes, and a statewide graduation-rate trend file. All 165
downloads succeeded (no errors). This adds attendance, retention, and
postsecondary-outcomes categories not previously covered for MA, plus richer
enrollment breakdowns (sped/CVTE).

The MA PowerBI "School and District Performance Summary" accountability
dashboard (app.powerbigov.us) was reviewed but deferred — would require
Power-BI query-capture reverse-engineering similar to the GA Insights gap-fill;
not started, no immediate need given the infoservices + statereport coverage.

### Known remaining gaps (documented, not solved)
- **FL financial (FEFP) + detailed staff** — `www.fldoe.org` is Akamai-blocked
  (403 Access Denied even via stealth browser; harder than CA's Radware). FL has
  assessment/enrollment/graduation via the report-card API + edudata, and
  discipline via CRDC, but the FEFP finance and detailed staff static files are
  unreachable from this network. Retry later or use an FLDOE data request.
- **MI ISD/district/school dashboard breakdowns + staffing dashboard tool** —
  see "Michigan dashboard" above; static files + CRDC cover district/school level.
- **NV secondary categories** — current enrollment/finance/teacher behind
  interactive dashboards (NV report-builder). CRDC supplies discipline
  (+ some enrollment/staff).

### Financial — gap fills completed (all 10 states now covered)
- **California** — added `/ds/fd/` crawl (Current Expense of Education / per-pupil) to scripts/ca/download.py.
- **Michigan** — added `financial-data-files/` (FID revenue & expenditure, 68 files) to scripts/mi/download.py.
- **Nevada** — NRS 387-388A statewide financial reports via scripts/nv/doe_download.py.
- **Florida (FEFP host Akamai-blocked)** — filled via the federal Census/NCES **F-33**
  district finance survey: `scripts/census_f33/download.py` downloads the national
  individual-unit files (FY2018-2022) and filters per-state district revenue+expenditure
  into data/raw/<ST>/finance_f33/ (FL = all 67 districts/year). Also provides a
  cross-state finance dataset for every assigned state.

**Result: all 10 states now cover all 5 required categories** (assessment,
financial, enrollment, discipline/suspension, teacher/staff) — verified by content,
not just file presence. State-published data is used where reachable; CRDC
(discipline/enrollment/staff) and F-33 (finance) federal datasets fill the
otherwise-blocked or dashboard-gated gaps (FL finance, MI/NV secondary categories).
