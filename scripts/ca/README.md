# The below is a template to use for README files for each State

- State: "CA"
- Last Scraped: "2026-07-08"
- Difficulty Rating for Scraping: "B"
- Short Notes: "cde.ca.gov publishes clean fixed-width bulk files, but the download pages sit behind a Radware bot check that needs a stealth browser to pass."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/ca/download.py                # CDE bulk files
python scripts/ca/assessment_download.py     # CAASPP/ELPAC research files
python scripts/ca/local_portals_download.py  # DataSF + Oakland Open Data
```

California is the best-structured source in the collection: CDE publishes assessment,
enrollment, staff, finance (SACS) and school directory as documented fixed-width or
tab-delimited bulk files, at state, district and school level. CAASPP and ELPAC statewide
research files come separately and are the assessment backbone.

The Radware captcha on `cde.ca.gov/ds/ad/` is defeated with a stealth Playwright context; once
past it the files themselves are plain HTTP.

Output layout: `data/raw/ca/{assessment,enrollment,staff,finance,directory,local_portals}/`.

## Known Issues
- Radware bot detection on the CDE download pages; a plain requests session gets blocked and needs the stealth browser path.
- Fixed-width files need the accompanying record layout to parse; layouts are published separately per dataset and are not all captured.

## Future Improvements
- Local portals currently cover San Francisco and Oakland only - other California districts run Socrata instances worth adding.
- Parse the fixed-width files into tidy CSVs at download time rather than leaving that to the consumer.
