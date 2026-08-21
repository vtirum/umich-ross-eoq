# The below is a template to use for README files for each State

- State: "NM"
- Last Scraped: "2026-08-13"
- Difficulty Rating for Scraping: "B"
- Short Notes: "web.ped.nm.gov is static and unusually well disaggregated - the best demographic coverage of any state in this collection - but much of it is legacy .xls that openpyxl cannot read."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/nm/download.py
```

New Mexico publishes accountability and directory data as files on `web.ped.nm.gov`. 232 of 233
files download cleanly, 429 MB, and **195 carry verified demographic columns** - ELL 190,
race 160, FRL 151, gender 148, IEP 124. That is the best-disaggregated state here.

Achievement-by-year publishes ELA/Math/Science proficiency as "attenuated" summaries plus
By-Assessment and By-SubTest-and-Grade breakdowns.

Note: a lot of New Mexico's files are legacy BIFF `.xls`, which openpyxl cannot read at all.
Adding an xlrd fallback in `common/verify_dims.py` took New Mexico from 149 to 195 files with
detected demographics (gender alone went 107 to 148). If demographic coverage for a state looks
implausibly low, check the file format first.

Output layout: `data/raw/nm/{assessment,enrollment,graduation,staff,finance,directory,other}/`.

## Known Issues
- Legacy .xls files need xlrd; anything reading these with openpyxl alone will silently see nothing.
- Entity-level detection under-reads some legacy layouts where the geography sits in a header block above the column row.

## Future Improvements
- The 'attenuated' summary files use a suppression scheme that is not documented in the files themselves; worth capturing the methodology note alongside them.
