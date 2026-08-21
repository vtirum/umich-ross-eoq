# The below is a template to use for README files for each State

- State: "AZ"
- Last Scraped: "2026-08-21"
- Difficulty Rating for Scraping: "C"
- Short Notes: "Data is plentiful and mostly plain JSON or Excel, but it is spread over four separate azed.gov sections plus a Power BI dashboard, and azed.gov sits behind Cloudflare."

## Other Longer Notes Below:
Vijay Tirumalai collection. Run from the repository root:

```bash
python scripts/az/azed_data_pages.py          # accountability, free/reduced-price, IDEA indicators
python scripts/az/report_cards_reports.py     # report cards API, FY2018-2025
python scripts/az/finance_static_download.py  # static finance files
python scripts/az/finance_dynamic_download.py # budget portal (Playwright)
python scripts/az/workforce_dashboards.py     # ADE Workforce (Power BI)
```

`azed.gov/data/public-data-sets` is a **hub page**, not a file page - it holds one PDF and
links out to the pages that actually publish data. Crawling only `accountability-research/data`
misses free/reduced-price lunch (`hns/frp`) and the IDEA Part B indicator profiles
(`specialeducation/sppapr`) entirely. `azed_data_pages.py` seeds from all three.

The report cards API (`azreportcards.azed.gov/api`) is the richest source: 23 report endpoints
per entity for state, 15,111 districts and 56,373 schools across FY2018-2025, no auth. About
71,500 JSON files per year, 11 GB total. `AZ_RC_YEARS=2019,2020` narrows a run.

Test scores are in `data/raw/az/accountability_research/` - 55 files, 713 MB, covering
2010-2025 unbroken. 2020 has AZELLA only because Arizona cancelled spring 2020 testing under
the federal COVID waiver. The current-format files carry school/district/county/state sheets
and 20 subgroups including gender.

Output layout: `data/raw/az/{accountability_research,reportcards,frl,sped_sppapr,finance,
finance_dynamic,student_membership,workforce,*_crdc,finance_f33}/`.

## Known Issues
- azed.gov is behind Cloudflare; link harvesting needs Playwright, and file downloads intermittently 403 (a retry with a same-site Referer usually clears it).
- The two 2025 SAFR volumes return 403 consistently and no current page links them - marked `unavailable_http_403` in the finance manifest.
- Arizona publishes no all-student discipline data. SPP/APR Indicator 4 is its own discipline source but is IDEA-scoped, LEA-level, and reports Met/Not Met against a suspension-rate target rather than counts. CRDC remains the only source of all-student suspension/expulsion counts.
- ADE publishes no downloadable staff file - SDER is PDFs and OACIS is a per-educator lookup. School-level staff comes from CRDC; state/county teacher demographics come from the Power BI Workforce dashboards.
- 36-70% of report-card JSON responses are `[]` (endpoint exists, nothing to report), and 188 of 752 logical datasets are empty for every entity.

## Future Improvements
- The 2010-2019 assessment workbooks predate the consolidated format and use several different schemas; a normalizer like `scripts/ks/normalize_assessment.py` would give one tidy table for the full 2010-2025 series.
- The report-card tree is ~240,000 empty `[]` files. Consolidating each (year, level, report) group into one CSV would cut file count enormously without losing data.
- `azed.gov/cte/data` has 134 files, checked and skipped as upload templates and policy PDFs; worth re-checking if CTE outcomes become a priority.
