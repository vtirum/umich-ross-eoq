# The below is a template to use for README files for each State

- State: "KS"
- Last Scraped: "2026-08-20"
- Difficulty Rating for Scraping: "D"
- Short Notes: "KSDE splits its data across two systems and neither is a plain download: Data Central is an ASP.NET report generator, and the test scores live in a separate Report Card site entirely."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/ks/download.py             # Data Central: 19 reports x state/district/county x years
python scripts/ks/assessment.py           # Report Card: annual full workbooks + counts API
python scripts/ks/normalize_assessment.py # -> assessment_all_years.csv
```

**Data Central** (`datacentral.ksde.gov/report_gen.aspx`) has no JSON API, but the generator
*is* the download endpoint: the final postback answers `Content-Type: application/vnd.ms-excel`,
so the three-step postback chain is replicated with plain requests and the body kept. 19 reports
x {State, Totals by District, Totals by County} x 2002-2025 = 627 files. It holds attendance,
graduation, enrollment, discipline, staff and directory - **but no test scores**.

**Test scores** are on `ksreportcard.ksde.gov`, a different KSDE system. The Report Card's
"Download Full Results" link resolves to `<YYYY>_<YYYY+1>_Assessment_Full_File.xlsx`; 11 annual
workbooks are published (2014-15 to 2024-25, 193 MB) and they are the complete dataset - state,
district and building level, every grade, subject and subgroup.

Two traps. Each workbook is a **two-year window** (`2023_2024` holds sheets `2023` *and* `2024`),
so every year but the endpoints is published twice and the copies differ because KSDE revises -
concatenating naively double-counts eight of ten years. And KSDE reshaped the layout roughly
every other year: six schemas across eleven files. `normalize_assessment.py` handles both and
writes `assessment_all_years.csv`, 2,209,296 rows, 2015-2025 (2020 absent, COVID).

Output layout: `data/raw/ks/{assessment,attendance,enrollment,graduation,discipline,staff,directory,other}/`.

## Known Issues
- Both KSDE hosts serve an incomplete TLS certificate chain - browsers repair it silently, Python does not - so certificate verification is disabled for those hosts (public data, no credentials sent).
- 2015-16 and 2016-17 assessment workbooks carry a `Population` column with both 'Accountability' and 'Report Card' rows; filter on it or those two years double-count.
- Gender is published in the assessment workbooks for 2014-15 and 2017-18 only. The other eight years, and the `getPerfChart2016` service, omit it. Gender otherwise appears only in the graduation report.
- The workbooks publish percentages only; the JSON service is kept purely as a counts supplement.

## Future Improvements
- Re-catalogue Kansas so the new full-file workbooks and `assessment_all_years.csv` appear in the search index (the current catalogue predates them).
- Expand the counts supplement to state level across all year anchors, so counts exist wherever percentages do.
