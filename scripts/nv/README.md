# The below is a template to use for README files for each State

- State: "NV"
- Last Scraped: "2026-08-20"
- Difficulty Rating for Scraping: "B"
- Short Notes: "nevadareportcard.nv.gov has a clean Data Interaction API covering six assessments with full subgroup breakdowns; the interactive report builder resists automation but is not needed."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/nv/download.py            # 6 assessments, All Students
python scripts/nv/subgroups_download.py  # same 6 by race, gender, IEP, EL, FRL
python scripts/nv/reportcard_full.py     # extended report card categories
python scripts/nv/doe_download.py        # doe.nv.gov topic pages
python scripts/nv/reorganize.py          # one-off tidy-up, idempotent
```

The Data Interaction API covers SBAC ELA/Math 3-8, CCR Grade 11, Science 5/8, Science 9/10,
NAA (alternate) and ELPA, at state, district and school level, with subgroups available via a
scope parameter.

Nevada's output grew by accretion across five scripts and needed flattening. `reorganize.py`
consolidates 9,061 single-record dashboard JSONs into one `reportcard/dashboard.csv`
(9,061 rows x 69 columns), moves twelve one-file `assessment_*` directories into
`assessment/<exam>.csv`, merges five per-script manifests into `manifest_all.csv`, and clears
empty directories. It is idempotent and was verified by spot-checking 300 records against source.

Output layout: `data/raw/nv/{assessment,reportcard,doe,*_crdc,finance_f33}/`.

## Known Issues
- The interactive report builder resists programmatic interaction; non-assessment categories come from doe.nv.gov static pages and CRDC instead.
- ACT has no subgroup breakdown in the API - that exam returns nothing for the subgroup pass.
- `reportcard/detail/` rows are headerless `cells` arrays with no column names in the payload or manifest, so they are deliberately left as JSON rather than converted to meaningless CSV columns.

## Future Improvements
- Recover column names for `reportcard/detail/` from the site's JavaScript so those files can be tabulated.
- The dashboard consolidation pattern in `reorganize.py` would suit any state whose API writes one record per file.
