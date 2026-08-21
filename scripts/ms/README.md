# The below is a template to use for README files for each State

- State: "MS"
- Last Scraped: "2026-08-11"
- Difficulty Rating for Scraping: "B"
- Short Notes: "mdek12.org is a plain static site, with one gotcha: files under /sites/default/files/ return 403 unless the request carries a same-site Referer."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/ms/download.py
```

Mississippi publishes through per-year pages (2018-19 through 2025-26) plus topic pages for
Assessment, Accountability, Reports, Diplomas and Staff. 178 files, 312 MB, all reachable with
plain requests.

The one trap: files served from `mdek12.org/sites/default/files/...` return **403 without a
same-site `Referer` header**. 20 files failed until the crawl engine retried with one; that
retry now lives in `common/static_site.py` and benefits every state using it.

Output layout: `data/raw/ms/{assessment,enrollment,graduation,staff,finance,other}/`.

## Known Issues
- Much of Mississippi's material is PDF, which the cataloguer skips - the apparent thinness of its demographic coverage is largely a PDF artefact.
- The 403-without-Referer behaviour is undocumented and will silently drop files if the retry is removed.

## Future Improvements
- Extract tables from the assessment and accountability PDFs.
- Per-year pages follow a predictable URL pattern; future years could be picked up automatically.
