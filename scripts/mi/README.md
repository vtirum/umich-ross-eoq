# The below is a template to use for README files for each State

- State: "MI"
- Last Scraped: "2026-06-12"
- Difficulty Rating for Scraping: "C"
- Short Notes: "MI School Data serves its bulk files from a CDN that is easy to read, but the interactive dashboards were not solved - the sub-state entity parameter format was not reverse-engineered."

## Other Longer Notes Below:
NOTE: `state_scrapers/MI/` already exists in this repository from another contributor's
collection. This is a separate Michigan collection and the two should be reconciled before
either is treated as canonical.

Run from the repository root:

```bash
python scripts/mi/download.py          # mischooldata.org CDN static files
python scripts/mi/dashboard_scrape.py  # legacy ASP.NET dashboard
```

`mischooldata.org` publishes assessment (M-STEP, SAT, PSAT), enrollment, graduation, finance
and staff as files on a CDN, at state, ISD, district and school level. Those are the backbone
of the collection and they download cleanly.

The interactive dashboards expose more granular breakdowns, but they key sub-state entities on
a `Common_Locations` parameter whose format was not worked out. State-level dashboard data is
captured; district and school data comes from the static files instead.

Output layout: `data/raw/mi/{assessment,enrollment,graduation,finance,staff,other}/`.

## Known Issues
- The `Common_Locations` parameter format for ISD/district/school dashboard queries was not reverse-engineered, so dashboard data is state-level only.
- Duplicate coverage with the existing `state_scrapers/MI/` collection in this repo.

## Future Improvements
- Work out the `Common_Locations` encoding to unlock sub-state dashboard breakdowns.
- Reconcile with the existing MI collection and keep whichever is more complete per category.
