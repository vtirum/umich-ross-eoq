# 13-State Education Data — Coverage Matrix & Collection Plan

Reconnaissance for expanding the pipeline from AZ + FL to 13 states:
**California, Utah, Arizona, Florida, Nevada, Massachusetts, New York, Georgia,
Pennsylvania, Michigan** (original 10) plus **Minnesota, Indiana, Missouri**.

Target data categories (per the project's First Task):
Test scores (ELA / Math / Science, + AP/ACT/SAT where available), Financials,
Teacher/staff records, Enrollment, Suspensions/Discipline. Where a source offers
breakdowns by **race, gender, IEP/504, or EL**, those are collected too.

Collection method legend:
- **API** — structured JSON/REST endpoints (fast, deep, cleanest). Pattern proven on AZ & FL report cards.
- **STATIC** — bulk downloadable files (CSV / Excel / fixed-width / Access DB). Often *all entity levels in one file* — highest value-per-effort.
- **DASHBOARD** — Tableau / Power BI / interactive portal; requires reverse-engineering (à la FL edudata) or embedding-API extraction.
- **FILE-LISTER** — a form that *filters a catalogue of bulk files* rather than
  rendering a report. Looks like a dashboard, behaves like STATIC once you submit it.
  (MN's MDE Analytics; see "Lessons" below — mistaking one for a dashboard cost us
  5.2 GB of Minnesota assessment data on the first pass.)

---

## Summary matrix

| State | Primary source(s) | Method | Entity depth | Notes |
|---|---|---|---|---|
| **California** | `cde.ca.gov/ds/ad/` (Radware captcha — DEFEATED) | **STATIC** (bulk fixed-width) | state→district→school | DONE — 216 files, 6.09 GB, 2019-2025. The Radware captcha was bypassed with a **stealth browser fingerprint** (mask `navigator.webdriver` + real UA/viewport/timezone/locale via Playwright) + gentle pacing; page links resolve to fixed-width files on `www3.cde.ca.gov/demo-downloads/` (no captcha on the file host). Covers enrollment (census), staff/CBEDS-CALPADS + assignments (TAMO), graduation cohort (ACGR/FYCGR), discipline/suspension, FRPM poverty, EL, student groups. All statewide files carry AggregateLevel + County/District/School codes (all levels). Assessment scores ALSO collected (scripts/ca/assessment_download.py): Smarter Balanced ELA/Math, CAA alternate, CAST science statewide research files from `caaspp-elpac.ets.org`, 2019-2025 (2020 absent = COVID). The on-page links are JS placeholders; real files follow `<pfx>_ca<year>_all_<fmt>_v<N>.zip` ("all" = every district+school) — constructed directly + version-probed, no form-driving. SB 2024 = 4.05M score rows w/ County/District/School codes. |
| **Utah** | `schools.utah.gov/datastatistics/reports.php` (STATIC); Data Gateway (Tableau) | **STATIC** + **DASHBOARD** | state→district→school | DONE — 216 files, 107 MB, 2019-2025. reports.php publishes ~307 direct Excel/PDF reports under `_reports_/_<category>_/` covering assessment, enrollment, educators, graduation/dropout, class size, nutrition, schools — a clean static scrape. **The Data Gateway turned out NOT to be optional:** the static reports break proficiency out by race, disability and ELL but *never by gender*. The public Data Gateway Tableau view does. `scripts/ut/datagateway_proficiency.py` reads it through the official Tableau Embedding API v3 in-page (`getSummaryDataAsync`, `applyFilterAsync` to iterate School Year — the URL year segment is ignored), yielding 234 rows = 6 years (2018-19…2024-25, no 2019-20/COVID) × 13 categories × 3 subjects incl. Male/Female. State-level only; no LEA/school gender is published anywhere. |
| **Arizona** | `azreportcards.azed.gov` API; `azed.gov` finance | **API** + STATIC | state→district→school | ✅ DONE — report cards API, accountability, finance scrapers built. |
| **Florida** | `edudata.fldoe.org` (report cards API + Tableau); `fldoe.org` | **API** + DASHBOARD + STATIC | state→district→school | ✅ DONE — report_cards API (23k files), edudata Tableau extractor (122 tables), static scraper. |
| **Nevada** | `nevadareportcard.nv.gov` (Data Interaction API) | **API** | state→district→school | DONE, **including subgroups.** Six exam types (SBAC `e24`, CCR gr-11 `e25`, Science 5/8 `e30`, Science 9/10 `e29`, NAA `e31`, ELPA `e39`) × All Students **and** × demographic subgroups, 967 orgs × 7 years. The breakthrough was a Playwright network capture on `/DI/nevada`: clicking the Achievement section revealed `summaryCSV` accepts `subgroups=gender,ethnicity,iep,lep,frl`, returning one row per group (up to 17: All + Female/Male/Unknown + 7 ethnicities + IEP/Not + EL/Not + FRL/Not) at state, district **and** school level (615 orgs carry subgroup rows for 2024-25 SBAC; smaller schools are privacy-suppressed). ACT is the one exception — the portal exposes no subgroup breakdown for it. Non-assessment categories come from `doe.nv.gov` static pages + CRDC. |
| **Massachusetts** | `profiles.doe.mass.edu/statereport/` | **STATIC** via ASP.NET postback replication | district→school | DONE — 158 tables, 156,931 rows, 2019-2025, district + school. Each statewide report renders a full HTML data table; year/level filters are ASP.NET postbacks with no GET API — replicated with `requests` (extract `__VIEWSTATE` + POST dropdown values; no Playwright). Reports: MCAS + participation (assessment), enrollment (×3), staff (salaries, race/gender, grade-subject), per-pupil finance, graduation, dropout, SSDR discipline. Note: report-type values vary in case across reports (District vs DISTRICT). 2020 MCAS absent (COVID). |
| **New York** | `data.nysed.gov/downloads.php` | **STATIC** (per-year MS Access DB) | state→district→school | **Single Report Card Database download per year = everything** (enrollment, assessment ELA/Math/Sci/Regents, grad, staff, attendance, suspensions, expenditures). Highest ROI. |
| **Georgia** | `download.gosa.ga.gov` (STATIC) + `georgiainsights.gadoe.org/data-downloads/` (Power BI → Azure blob) | **STATIC** + **DASHBOARD-discovered blob** | district→school | DONE, two complementary sources. (1) GOSA repo: per-year/domain spreadsheets (Milestones, ACT/SAT/AP, enrollment, finance, grad, dropout, personnel, attendance). (2) GaDOE Insights: 405 files on an Azure blob, discovered by capturing the Power BI report's query responses — CCRPI accountability, WIDA ACCESS ELL, EOC course-level, FTE enrollment, Whole Child, CTAE. |
| **Pennsylvania** | `futurereadypa.org/Home/DataFiles`; `pa.gov/.../data-and-reporting`; data.gov | **STATIC** (Excel) + DASHBOARD | state→district→school | PSSA/Keystone, enrollment, staff, finance, grad. Future Ready PA Index data files + PDE reports + PA open-data (Socrata). |
| **Michigan** | `mischooldata.org` (CDN static + dashboards) | **STATIC** done; dashboard not solved | state→ISD→district→school | DONE for static archive (10 files: historical MEAP/MME assessment zips + layouts, on the michigan.gov CDN). Current enrollment/finance/educator/M-STEP live in the interactive "custom dataset builder" — **gap-fill ATTEMPTED, not solved.** The site is an Umbraco CMS behind a **Cloudflare challenge**; the CMS content pages expose no data API, and the real dashboards are separate JS apps whose data endpoint was not located (no non-CMS JSON/CSV traffic captured, even with a stealth browser). Realistic path: locate the dashboard viz endpoint via the live builder, or a CEPI data request. |

### Expansion states (added 2026-07)

| State | Primary source(s) | Method | Entity depth | Notes |
|---|---|---|---|---|
| **Minnesota** | `pub.education.mn.gov/MDEAnalytics` (FILE-LISTER); `rc.education.mn.gov` (WebFOCUS JSON API) | **STATIC** + **API** | state→county→district→school | DONE — **828 files, 5.2 GB** from MDE Analytics + 45 JSONL report-card files (194 MB). MDE Analytics is the primary source and was **missed on the first pass** (see Lessons): its 59 topics are `DataTopic.jsp?TOPICID=N` pages, most of which are *file listers* — pick Test/Year/Subject/Grade, press "List files", get direct `.xlsx` links. 600 assessment files span 1998-2025 (MCA, MTAS, Alt-MCA, MOD, GRAD, BST, ACCESS/Alt-ACCESS, TEAE, MTELL, SOLOM, WIDA), each with **State/County/District/School sheets** and `Group Category` + `Student Group` columns covering Race/Ethnicity, Gender, Special Education, English Proficiency, Economic Status, Homeless, Migrant, Military Family and SLIFE — the richest disaggregation of any state collected. The Report Card API (`WFServlet?IBIF_ex=rptcard_getdata_<report>`) adds 16 report types at state+district+school (27,344 org-records). |
| **Indiana** | `in.gov/doe/it/data-center-and-reports` (STATIC); `in.gov/dlgf` (STATIC); EdData (Power BI Gov) | **STATIC** | state→corporation→school | DONE — 330 files (258 MB) from the Data Center + **96 files (157 MB)** recovered by a later audit. Data Center covers ILEARN 3-8 + Biology (incl. disaggregated), IREAD, I AM, SAT, ACT, ECA, enrollment/demographics back to 2006, attendance/chronic absenteeism, graduation, federal accountability, teacher statistics. **296/330 files carry verified demographic breakdowns** (race 296, IEP 223, FRL 141, ELL 129, gender 111) — the best-disaggregated static corpus collected. The audit additions live *outside* the DOE site: **`in.gov/dlgf`** (Dept of Local Government Finance — certified budgets, levies, tax rates by district/fund 2022-26), College Readiness/Going cohort datasets 2017-24, and Public Special Education Data SY2020-24. |
| **Missouri** | `apps.dese.mo.gov/MCDS` (STATIC) | **STATIC** | state→district→building | DONE — **251/252 files, 503 MB** (the one failure returns 0 bytes at source). MCDS category pages render their file links in JS, so a browser harvests the `FileDownloadWebHandler.ashx?filename=…` links and plain `requests` downloads them (handler is not bot-gated and supplies real filenames via Content-Disposition). Covers MAP by content-area/grade **and subgroup**, enrollment/demographics to 1991, per-pupil expenditures, ASBR finance, faculty/certification/ratios, cohort graduation, discipline incidents. **109/252 files carry verified demographics — but gender appears in only 3** (see Known gaps). A 570-page audit found no substantive additions. |

---

## Method tally

- **Pure/primary STATIC bulk** (easiest, highest ROI): **NY, CA, MA, GA, MI, PA, IN, MO** (+ **MN** once the file-lister is understood)
- **Pure API** (clean, proven pattern): **NV** (+ AZ, FL done), **MN** report card
- **Dashboard-heavy / hardest**: **UT** (+ PA & MI have dashboard components alongside static)
- **Defeated bot protection**: CA (Radware), MO/MN wrappers, FL (Akamai, via Wayback)
- **Undefeated bot protection**: MN MDE Analytics *report-runner* topics (PerimeterX), IN EdData (Power BI Gov cloud)

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

### Minnesota (MDE) — FILE-LISTER + API
- **MDE Analytics (primary):** `https://pub.education.mn.gov/MDEAnalytics/Data.jsp`
  → 59 topics at `DataTopic.jsp?TOPICID=<N>`. Each topic embeds a WebFOCUS app; the
  data topics (Assessment `1`, Graduation `545`, North Star `450`, Student `2`,
  Schools/Districts `4`, ACT `87`, Course Taking `588`) are **file listers** whose
  "List files" button POSTs to `WFServlet` and returns a table of direct
  `/MDEAnalytics/DataFileDownload?...` links. `scripts/mn/mde_analytics_files.py`.
- **Report Card API:** `https://rc.education.mn.gov/ibi_apps/WFServlet?IBIAPP_app=rptcard_reports&IBIF_ex=rptcard_getdata_<report>&orgId=&groupType=state|district|school&year=`
  Statewide org = `999999000000`; org list via `rptcard_getfilter_orglist.fex?reportCode=N`.
  Each response embeds a 5-year trend, so one call per org per report. Not bot-gated.
- **Blocked:** the *report-runner* topics (Discipline `133`, Finance/UFARS `20`/`79`/`81`,
  MFR `9`) sit behind PerimeterX — "Run Report" fires a `js_zpsbd3` challenge and the
  report never generates headlessly. Backstopped by CRDC + Census F-33.

### Indiana (IDOE) — STATIC
- Data Center: `https://www.in.gov/doe/it/data-center-and-reports/` (+ `/data-reports-archive/`)
- Files resolve to `https://www.in.gov/doe/files/*.xlsx`.
- **Also crawl these — they are NOT under `/doe/it/`:**
  `https://www.in.gov/doe/school-operations/finance/`,
  `https://www.in.gov/doe/students/special-education/`, and
  **`https://www.in.gov/dlgf/`** (a *different agency* — district budgets/levies/tax rates).
- **Blocked:** Form 9 finance is only in EdData (`eddata.doe.in.gov`), a Power BI
  **Government cloud** embed (`app.powerbigov.us`, querydata on
  `analysis.usgovcloudapi.net`). It renders only inside its wrapper page and Playwright
  never paints the visuals (headless *and* headed), so only `modelsAndExploration`
  metadata returns. Teacher licensing (LVIS360) is search-only, no bulk export.

### Missouri (DESE) — STATIC
- MCDS portal: `https://apps.dese.mo.gov/MCDS/home.aspx?categoryid=<0-7>&view=2`
  (categories 0/1/6/7 return the same default set; 2/3/4/5 are distinct).
- File links are JS-rendered → harvest with a browser, download with `requests`:
  `FileDownloadWebHandler.ashx?filename=<hash><name>.xlsx`.
- **Not usable:** `SSRS_Print.aspx?Reportid=…` are per-district **parameter forms**,
  and the wrapper ignores SSRS's `rs:Format=EXCELOPENXML|EXCEL|CSV` export params
  (all three return the same HTML). The statewide bulk files already contain this data.

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

### Known remaining gaps — expansion states
- **MN discipline + finance/UFARS** — MDE Analytics *report-runner* topics behind
  PerimeterX (see per-state detail). Filled by CRDC (discipline) and Census F-33
  (finance); MN's own fiscal-transparency report is also captured via the Report Card
  API at state/district/school (5,318 school sites).
- **IN Form 9 finance** — Power BI Government cloud, not extractable
  (`scripts/in/eddata_dashboards.py` exists and is documented as non-working).
  Partly compensated by the `in.gov/dlgf` budget/levy/tax-rate files; otherwise F-33.
- **IN teacher licensing** — LVIS360 is search-only, no bulk export. CRDC covers staff.
- **MO gender** — only 3 of 252 files carry a gender dimension (vs 96 with race),
  confirmed by reading file contents. This is a genuine state-publication gap, the same
  shape as Utah's; gender-disaggregated MO data requires CRDC.
- **MN ACT subgroups / NV ACT subgroups** — neither portal exposes ACT by subgroup.

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

### Financial — gap fills completed (all original 10 states covered)
- **California** — added `/ds/fd/` crawl (Current Expense of Education / per-pupil) to scripts/ca/download.py.
- **Michigan** — added `financial-data-files/` (FID revenue & expenditure, 68 files) to scripts/mi/download.py.
- **Nevada** — NRS 387-388A statewide financial reports via scripts/nv/doe_download.py.
- **Florida (FEFP host Akamai-blocked)** — filled via the federal Census/NCES **F-33**
  district finance survey: `scripts/census_f33/download.py` downloads the national
  individual-unit files (FY2018-2022) and filters per-state district revenue+expenditure
  into data/raw/<ST>/finance_f33/ (FL = all 67 districts/year). Also provides a
  cross-state finance dataset for every assigned state.

**Result: all 13 states now cover all 5 required categories** (assessment,
financial, enrollment, discipline/suspension, teacher/staff) — verified by content,
not just file presence. For the three expansion states: MN via MDE Analytics +
Report Card API (+ CRDC/F-33 for the PerimeterX-blocked discipline/finance topics),
IN via the Data Center + DLGF (+ F-33 for Form 9), MO via MCDS. State-published data is used where reachable; CRDC
(discipline/enrollment/staff) and F-33 (finance) federal datasets fill the
otherwise-blocked or dashboard-gated gaps (FL finance, MI/NV secondary categories).

---

## Coverage audit & LLM-assisted discovery (2026-07)

After MN/IN/MO were "done", a systematic audit re-swept all three for missed files,
with emphasis on demographically disaggregated data. Three reusable tools came out of
it (`scripts/common/`), plus some hard-won calibration about what an LLM is good for.

### The tools

| Tool | What it does | Verdict |
|---|---|---|
| `llm_assist.py` | Local Ollama (qwen2.5:14b) batch-classifies file labels → category + demographic dims; also ranks page links for crawl priority. Disk-cached; nothing leaves the machine. | **Good for categories.** MO's mis-filed "other" bucket: 135 → 10. |
| `verify_dims.py` | Opens each downloaded file and detects race/gender/IEP-504/ELL/FRL from **actual headers and values** (handles wide *and* long "Student Group" layouts). | **The authoritative check.** Use `verified_dims`, never `llm_dims`. |
| `site_audit.py` + `fetch_candidates.py` | Crawl seeds → extract file links → diff against existing manifest → classify → download. | Found IN's 96 missing files. |

### What the LLM is and isn't good for

Measured against file contents, title-based dimension guessing was wrong constantly —
and mostly in the direction of **under-reporting**:

| | agree | over-claimed | **missed** |
|---|---|---|---|
| Indiana | 142 | 2 | **154** |
| Missouri | 66 | 2 | **43** |

A concrete over-claim: MO's "APR Summary by Districts" was tagged
`race|gender|iep_504|ell|frl` from its title; the file actually carries only race and
ELL. Titles are not evidence. Equally, `verify_dims.py` has its own blind spot — it
detects demographic *columns*, so blank submission templates match too (MO's MOSIS
batch file defines `Gender: 0 = female, 1 = male` but holds no records). Check row
counts alongside dimensions.

**Where the LLM did not help at all:** every genuinely hard problem in this project was
a *transport* problem, not a *comprehension* problem — a hidden POST interface (MN
file-listers), an undocumented API parameter (NV `subgroups=`), bot protection
(PerimeterX, Radware, Akamai), or a cross-origin embed (Power BI Gov). No amount of
HTML reading solves those; network capture does. The LLM's value is triage over
*already-extracted* links, not discovery.

### Verified demographic coverage (from file contents)

| State | files w/ demographics | race | IEP/504 | ELL | FRL | gender |
|---|---|---|---|---|---|---|
| Indiana | 296 / 330 | 296 | 223 | 129 | 141 | 111 |
| Missouri | 109 / 252 | 96 | 68 | 94 | 37 | **3** |

Minnesota is not in this table because its disaggregation is *inside* every assessment
file (`Group Category` / `Student Group` columns) rather than varying file-to-file.

### Audit outcomes

- **Indiana — real gap, 96 files / 157 MB recovered.** Root cause: the original crawl
  seeded only `/doe/it/`. Finance lived at `/doe/school-operations/finance/` and, more
  importantly, at **`in.gov/dlgf`** — a different agency entirely.
- **Missouri — no gap.** 570 pages crawled; of 131 new candidates only 45 were
  spreadsheets, and those are MOSIS submission templates, file-layout "translation
  guides", and planning calculators. The MCDS pull was already complete.
- **Minnesota — the big one**, found by user report rather than by the audit: 828 files
  / 5.2 GB (see Lessons).

### Lessons (cost us real data)

1. **A form that filters files is not a dashboard.** MN's MDE Analytics was written off
   as "PerimeterX-blocked report-runner" after one headless probe. It is mostly a
   *file lister*; the real browser passed the bot check and the "List files" button
   returned direct `.xlsx` links. Cost: 5.2 GB, found only because the user pushed back
   twice. **Always press the submit button in a real browser before concluding a portal
   yields nothing.**
2. **One section ≠ the whole site, and the whole site ≠ the whole agency.** IN's finance
   data was on a sibling agency's domain (`in.gov/dlgf`).
3. **Verify disaggregation by reading files, not filenames.** Both directions of error
   are common; under-reporting is the more damaging one.
4. **Long scrapes degrade.** MN's report-card run fell from ~1.5 s/request to ~208
   s/request after ~9 hours (server-side throttling amplified by `Retry(total=5,
   backoff_factor=1.5)` + 60 s timeout turning each hiccup into a 5-minute stall).
   Fail fast (1 retry, 20 s timeout) and make every scraper resumable.

### CA / UT / MI additions — cross-checked against vetted source inventories
Three source-inventory documents (California/Utah/Michigan Education Data Sources
v2) were cross-referenced against the existing scripts. Gaps found and filled:

- **California school directory** — `cde.ca.gov/ds/si/ds/pubschls.asp` (Public
  Schools & Districts) and `/ds/si/ps/` (Private School Data, 10 files: directory +
  enrollment-by-grade) added to `scripts/ca/download.py`'s seed pages (PAGE_PREFIX
  extended to `/ds/si/`). The pubschls.asp file itself is generated dynamically
  (button-triggered, not a static link) and was not captured — documented gap,
  same class of limitation as the MI dashboard builder.
- **California local portals** — new `scripts/ca/local_portals_download.py`:
  - **DataSF** (`data.sfgov.org`, Socrata) — the "Schools" dataset (locations).
    SFUSD academic data is not on DataSF (confirmed; covered by statewide CDE).
  - **Oakland Open Data** (`data.oaklandca.gov`, Socrata) — genuine OUSD
    academic-performance datasets under the "Equity Indicators" category:
    enrollment (preschool, student-population representation), discipline
    (chronic absenteeism, suspensions, disconnected youth), assessment (3rd-grade
    ELA, A-G completion, high school readiness, linked learning, physical
    fitness), and staff (teacher experience/turnover, staffing representation,
    academy attrition) — 16 CSVs via the Socrata `/resource/<id>.csv` export.
    A handful of same-named Oakland catalog entries (Education, Enrollment,
    Achievement, Program Access, Teachers, Staffing) are Socrata "story" assets
    (narrative dashboards), not downloadable tables, and are excluded.
  - **LAUSD Open Data** — the Catalog/Dashboard lives behind an authenticated
    `my.lausd.net` / `achieve.lausd.net` Tableau-style app; not collected (same
    class of gap as MA's PowerBI accountability dashboard — would need
    network-capture, see Collection Method 6).
- **Utah Open Data** — new `scripts/ut/opendata_download.py`: queries the
  `opendata.utah.gov` Socrata catalog (Education category), keeps only datasets
  whose `Dataset-Information_Agency` metadata is "State Office of Education"
  (filters out Higher-Ed/Census/other agencies sharing the category), and
  downloads each via CSV export — 123 USBE-owned datasets (assessment, enrollment,
  graduation, finance, staff), many of which are historical per-district/charter
  breakouts not present in the bulk `reports.php` files collected by
  `scripts/ut/download.py`.
- **Michigan** — `scripts/mi/download.py` already crawls all 15 mischooldata.org
  `*-data-files` pages including `financial-data-files/`, so the inventory's
  Tier-1 sources (Bulletins 1014/1011, EEM, historical MEAP/MME, additional
  staffing) were already covered. The two Tier-L local portals checked did not
  yield a usable addition: the City of Detroit ArcGIS Hub only has school
  *locations* (the inventory itself notes this isn't academic data), and the
  DPSCD "Open Data Library" page referenced in the inventory (`detroitk12.org`)
  404s on the current site — and per the inventory's own caveat, it only
  re-serves MDE/MI School Data files already collected here. No new MI scraper
  was added; documented as a non-gap.
