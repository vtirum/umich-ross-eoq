# The below is a template to use for README files for each State

- State: "MN"
- Last Scraped: "2026-08-19"
- Difficulty Rating for Scraping: "D"
- Short Notes: "MDE Analytics looks like an empty report builder until you press Submit - it is actually a file lister sitting on 828 downloadable files. Some other MDE forms are behind PerimeterX."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/mn/mde_analytics_files.py    # pub.education.mn.gov/MDEAnalytics file listers
python scripts/mn/report_card.py            # rc.education.mn.gov WebFOCUS JSON API
python scripts/mn/report_card_subgroups.py  # report card subgroup breakdowns
```

The important lesson here: `pub.education.mn.gov/MDEAnalytics/Data.jsp` was initially dismissed
as blocked after a single headless probe. It is not blocked - it is a **file lister**, a form
that filters a catalogue of bulk files rather than generating a report, and it returns nothing
until the submit button is actually pressed. Pressing it recovered **828 files, 5.2 GB**, which
is most of Minnesota's collection. Do not conclude a portal is empty without submitting its form.

The Report Card (`rc.education.mn.gov`) is WebFOCUS, reachable as
`WFServlet?IBIAPP_app=rptcard_reports&IBIF_ex=rptcard_getdata_<report>`, returning JSON.

Minnesota's filenames are frequently meaningless - the download handler names 115 files
`000574.xlsx`, `000722.xlsx` and so on - which is what motivated the content-signature
cataloguer in `scripts/common/catalog_local.py`.

Output layout: `data/raw/mn/{assessment,enrollment,graduation,attendance,staff,finance,discipline,other}/`.

## Known Issues
- Discipline and UFARS finance forms are report-runners protected by PerimeterX (the `js_zpsbd3` beacon) and were not solved.
- Long runs degrade badly - request latency went from ~1s to 208s from a stale session plus `Retry(total=5, backoff=1.5)`. Fixed with a fail-fast session; keep runs bounded.
- 115+ files have opaque numeric names carrying no topic information; use the catalogue to find them.

## Future Improvements
- Revisit the PerimeterX-protected report-runners with a headed browser session.
- MDE Analytics has more file-lister forms than the three currently seeded; enumerate them systematically.
