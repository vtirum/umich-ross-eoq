# The below is a template to use for README files for each State

- State: "GA"
- Last Scraped: "2026-06-12"
- Difficulty Rating for Scraping: "B"
- Short Notes: "download.gosa.ga.gov serves clean bulk files; the Insights dashboard turned out to be backed by a public Azure blob container, which is easier to read than the dashboard."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/ga/download.py            # download.gosa.ga.gov bulk files
python scripts/ga/insights_download.py   # GaDOE Insights (Azure blob behind the Power BI)
```

The Governor's Office of Student Achievement publishes per-year CSVs for assessment,
enrollment, graduation, discipline, finance and staff at district and school level. The
GaDOE Insights Power BI dashboard reads from a public Azure blob container; watching its
network traffic gave the container URL, and the files are downloadable directly from there -
no dashboard automation needed.

Output layout: `data/raw/ga/{gosa,insights,*_crdc,finance_f33}/`.

## Known Issues
- Blob container paths are undocumented and were found by observation; if GaDOE reorganises the container the script will need re-discovery.
- GOSA file naming is inconsistent across years, so year extraction relies on the filename rather than a field.

## Future Improvements
- Enumerate the blob container listing rather than relying on the observed set of paths, so new files appear automatically.
