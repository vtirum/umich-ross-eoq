# The below is a template to use for README files for each State

- State: "NY"
- Last Scraped: "2026-06-12"
- Difficulty Rating for Scraping: "C"
- Short Notes: "data.nysed.gov publishes one Microsoft Access database per year rather than flat files, so everything needs extracting from .accdb before use."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/ny/download.py
```

New York's report card data comes as a single Access database per school year from
`data.nysed.gov/downloads.php`, covering assessment, enrollment, graduation, staff and finance
at state, district and school level. The download itself is straightforward; the format is the
obstacle.

Output layout: `data/raw/ny/`.

## Known Issues
- Data is in .accdb, which needs mdbtools or a driver to read; nothing downstream in this repo parses it yet, so the catalogue sees almost nothing for New York.
- Only 38 catalogued files, which understates New York's actual coverage - the content is inside the databases.

## Future Improvements
- Extract each Access database to CSV per table at download time. This would make New York searchable in the catalogue and is the single highest-value improvement for this state.
