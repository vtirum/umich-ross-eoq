# The below is a template to use for README files for each State

- State: "PA"
- Last Scraped: "2026-06-11"
- Difficulty Rating for Scraping: "A"
- Short Notes: "futurereadypa.org and the PDE reports pages publish plain Excel files with stable URLs. Simple, but the collection here is thin and worth expanding."

## Other Longer Notes Below:
NOTE: `state_scrapers/PA/` already exists in this repository from another contributor's
collection, which appears more complete than this one. Reconcile before treating either as
canonical.

Run from the repository root:

```bash
python scripts/pa/download.py
```

`futurereadypa.org/Home/DataFiles` publishes assessment (PSSA, Keystone), enrollment,
graduation, finance and staff as Excel files; `pa.gov` data-and-reporting pages and data.gov
add more. No session handling or bot detection.

Output layout: `data/raw/pa/`.

## Known Issues
- Only 70 files collected - thin relative to what Pennsylvania publishes, and thinner than the existing `state_scrapers/PA/` collection in this repo.
- Duplicate coverage with that existing PA collection.

## Future Improvements
- Reconcile with the existing PA collection and keep the more complete one.
- The PDE dashboard side was not attempted at all.
