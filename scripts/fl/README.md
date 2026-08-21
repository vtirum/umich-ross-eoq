# The below is a template to use for README files for each State

- State: "FL"
- Last Scraped: "2026-08-11"
- Difficulty Rating for Scraping: "D"
- Short Notes: "Akamai returns 403 to automated clients on fldoe.org even from a stealth browser, so the bulk files come via the Wayback Machine; the report cards API and Tableau exports are clean."

## Other Longer Notes Below:
Run from the repository root:

```bash
python scripts/fl/scrape.py          # static FLDOE data pages
python scripts/fl/report_cards.py    # report cards API (incl. GetTGELA: assessment by gender/race/IEP/ELL)
python scripts/fl/edudata_export.py  # edudata.fldoe.org Tableau API
python scripts/fl/fldoe_download.py  # bulk files proxied through the Wayback Machine
```

Three different mechanisms. The report cards API on `edudata.fldoe.org` is plain JSON and
carries the demographic breakdowns. The Tableau views expose their underlying worksheets
through the Embedding API v3. The bulk EDW files on `fldoe.org` are the problem: Akamai
blocks automated clients outright, so `fldoe_download.py` fetches them from the Wayback
Machine instead, which has snapshots of attendance, enrollment, staff, graduation and the
2025 FAST results.

Output layout: `data/raw/fl/{report_cards,edudata,fldoe,static,*_crdc,finance_f33}/`.

## Known Issues
- fldoe.org returns HTTP 403 from Akamai to requests and to stealth headless Chromium; the Wayback proxy is a workaround, not a fix, and only reaches files that were snapshotted.
- Florida finance (FEFP) is not collected from the state at all for the same reason - Census F-33 fills the gap.
- Wayback snapshots lag the live site, so the most recent release of a file may not be available.

## Future Improvements
- A headed-browser path with a real profile might get past Akamai and reach FEFP directly.
- The Tableau export currently pulls summary worksheets; some views have finer underlying data reachable with applyFilterAsync.
