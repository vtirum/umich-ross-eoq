# The below is a template to use for README files for each State

- State: "IN"
- Last Scraped: "2026-08-11"
- Difficulty Rating for Scraping: "D"
- Short Notes: "The IDOE Data Center bulk files are straightforward, but Form 9 finance lives in a Power BI on the US Government cloud that will not render under automation."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/in/download.py             # IDOE Data Center + DLGF bulk files
python scripts/in/eddata_dashboards.py    # EdData Power BI (does not currently work - see issues)
```

`in.gov/doe/it/data-center-and-reports` publishes assessment (ILEARN, IREAD, ISTEP),
enrollment, graduation, attendance, discipline and staff as per-year Excel files at state,
corporation and school level. `in.gov/dlgf` adds local government finance.

Form 9 - the district financial report - is only published through EdData, a Power BI hosted
on `app.powerbigov.us` (the US Government cloud, backed by `analysis.usgovcloudapi.net`).
The script for it exists and the DSR decoding logic is shared with Arizona, but the report
renders only inside its own wrapper and never paints under Playwright, so no data comes back.
Indiana finance is currently covered by Census F-33 instead.

Output layout: `data/raw/in/{assessment,enrollment,graduation,attendance,discipline,staff,finance,other}/`.

## Known Issues
- EdData Power BI (Government cloud) does not render under Playwright; `eddata_dashboards.py` runs but returns nothing. Form 9 finance is not collected from the state.
- The LLM cataloguer under-reported Indiana demographic coverage badly (it missed 154 files that do carry breakdowns) - trust `verified_dims`, not `llm_topic`, for this state.

## Future Improvements
- Form 9 is also published as static PDFs per district on some corporation sites; a per-district crawl would be tedious but would close the finance gap.
- Retry the Government-cloud Power BI with a headed browser and a real profile - the wrapper may be checking something a headless context cannot present.
