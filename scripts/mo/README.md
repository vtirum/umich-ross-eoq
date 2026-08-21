# The below is a template to use for README files for each State

- State: "MO"
- Last Scraped: "2026-08-19"
- Difficulty Rating for Scraping: "A"
- Short Notes: "MCDS publishes plain bulk files with stable URLs. Easiest state in the collection; the only real limitation is that Missouri barely publishes gender breakdowns."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/mo/mcds_download.py
```

The Missouri Comprehensive Data System (`apps.dese.mo.gov/MCDS`) publishes assessment (MAP,
EOC), enrollment, graduation, attendance, discipline, staff and finance as ordinary downloadable
files at state, district and building level. No session handling, no bot detection, no form
replication - the whole state is one straightforward script.

Output layout: `data/raw/mo/{assessment,enrollment,graduation,attendance,discipline,staff,finance,other}/`.

## Known Issues
- Gender is essentially absent: only 3 of 252 files carry a gender breakdown. This is a genuine publication gap, not a collection failure - CRDC is the fallback.

## Future Improvements
- MCDS also has a parameterised report builder that can produce breakdowns not present in the bulk files; worth checking whether it exposes gender.
