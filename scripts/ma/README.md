# The below is a template to use for README files for each State

- State: "MA"
- Last Scraped: "2026-07-08"
- Difficulty Rating for Scraping: "C"
- Short Notes: "profiles.doe.mass.edu is ASP.NET WebForms; the reports are reachable by replicating the postback chain and carrying __VIEWSTATE across requests."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/ma/download.py               # profiles.doe.mass.edu state reports
python scripts/ma/infoservices_download.py  # doe.mass.edu/infoservices bulk files
python scripts/ma/mcas_subgroups.py         # MCAS results by student subgroup
```

School and District Profiles serves its reports through ASP.NET WebForms. There is no API, but
the postbacks are deterministic: carry `__VIEWSTATE` and `__EVENTVALIDATION` forward across
requests and the report export returns a real file. Same technique as Kansas Data Central.

MCAS subgroup results are a separate pass because the subgroup selector is its own postback
dimension. `doe.mass.edu/infoservices` adds bulk enrollment, staff and finance files.

Output layout: `data/raw/ma/{assessment,enrollment,graduation,staff,finance,other}/`.

## Known Issues
- The Power BI accountability dashboard has been reviewed but not scraped. It would use the DSR capture-and-decode approach already proven for Arizona workforce.
- __VIEWSTATE is large and opaque; if the page's control tree changes the replicated postback chain breaks with no useful error.

## Future Improvements
- Scrape the accountability Power BI using `common/powerbi.py`.
- The postback replication is Massachusetts-specific; it and the Kansas equivalent could share a helper in `common/`.
