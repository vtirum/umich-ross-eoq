# The below is a template to use for README files for each State

- State: "UT"
- Last Scraped: "2026-07-08"
- Difficulty Rating for Scraping: "B"
- Short Notes: "USBE's static reports are easy, but they omit gender entirely - that had to come from a Tableau view on the Data Gateway."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/ut/download.py                 # USBE reports page bulk downloads
python scripts/ut/opendata_download.py        # opendata.utah.gov USBE datasets
python scripts/ut/datagateway_proficiency.py  # Data Gateway (Tableau): proficiency by gender
```

`schools.utah.gov/datastatistics/reports.php` publishes assessment, enrollment, graduation,
finance and staff as Excel and PDF. `opendata.utah.gov` is Socrata and adds USBE-owned datasets
with a clean API.

The static reports break out race, disability and ELL but **not gender**. Gender proficiency
comes instead from the Data Gateway Tableau view, read through the Embedding API v3
(`getSummaryDataAsync`, `applyFilterAsync`).

Output layout: `data/raw/ut/{assessment,enrollment,graduation,finance,staff,opendata,other}/`.

## Known Issues
- Gender proficiency from the Data Gateway is state-level only. LEA- and school-level gender is not published anywhere in Utah.
- The Tableau Embedding API path depends on the view's worksheet names; a dashboard redesign will break it.

## Future Improvements
- Check whether the Data Gateway exposes LEA-level gender through a different view or filter combination.
