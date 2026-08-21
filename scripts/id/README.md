# The below is a template to use for README files for each State

- State: "ID"
- Last Scraped: "2026-08-11"
- Difficulty Rating for Scraping: "C"
- Short Notes: "The report card is a Blazor app that ignores synthetic clicks, but it is backed by an unauthenticated JSON API that serves everything the UI shows."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/id/download.py     # sde.idaho.gov finance-transparency static files
python scripts/id/reportcard.py   # idahoreportcard.org export API
```

Two halves. `sde.idaho.gov` publishes finance and enrollment as ordinary files - ADA
(full-term/midterm/best-28), support units, enrollment by building/district/grade, revenues
and expenditures 2004-2024, annual statements of financial condition, staff salaries.

`idahoreportcard.org` is a Blazor application. Driving the UI failed repeatedly: strict-mode
selector collisions, open dropdowns overlaying the buttons underneath, and Blazor ignoring
`element.click()` because it listens for real pointer events. Abandoning the UI and probing
the JSON API directly worked - 38 measures across 29 breakdowns, including Male (53) and
Female (54). Requests that exceed the server's row limit return 400, so the script halves the
breakdown list recursively until each request succeeds.

Output layout: `data/raw/id/{finance,enrollment,reportcard,other}/`.

## Known Issues
- Much of the sde.idaho.gov material is PDF, which the cataloguer skips - the apparent gap in Idaho's demographic coverage is mostly PDFs, not missing data.
- The report card API enforces an undocumented response-size limit; the recursive halving works but makes request counts unpredictable.
- Blazor UI automation was abandoned; if the API changes there is no fallback path.

## Future Improvements
- Extract tables from the finance PDFs (they are text, not scans) to close the demographic gap.
- Cache the breakdown-splitting decisions so re-runs do not re-derive the working request sizes.
