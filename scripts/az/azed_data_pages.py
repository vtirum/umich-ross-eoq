"""
Download the file-bearing pages under azed.gov's Public Data Sets hub.

https://www.azed.gov/data/public-data-sets is a hub, not a file page: it links out
to the pages that actually publish data. We had only ever crawled one of them
(accountability-research/data), so three sources were missing entirely -

    accountability-research/data   assessment, graduation, dropout, Oct 1 enrollment
    hns/frp                        free and reduced-price percentages (poverty)
    specialeducation/sppapr/...    IDEA Part B SPP/APR indicator profiles, incl.
                                   Indicator 4 (suspension) - Arizona's own
                                   discipline data, which we had been taking from
                                   the federal CRDC extract instead

Link harvesting runs through Playwright because azed.gov sits behind Cloudflare and
plain requests get challenged intermittently; the files themselves download fine
over requests once you have the URLs.

Accountability output stays flat in data/raw/az/accountability_research/ next to the
files already there. The two new sources get their own directories, filed by
category the way the other states are.

    python scripts/az/azed_data_pages.py            # all three
    python scripts/az/azed_data_pages.py frl sped   # named sources only
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from common.static_site import run

HUB = "https://www.azed.gov/data/public-data-sets"

SOURCES = {
    "accountability": {
        "url": "https://www.azed.gov/accountability-research/data/",
        "out": Path("data/raw/az/accountability_research"),
        "flat": True,
    },
    "frl": {
        "url": "https://www.azed.gov/hns/frp/",
        "out": Path("data/raw/az/frl"),
        "flat": False,
    },
    "sped": {
        "url": "https://www.azed.gov/specialeducation/sppapr/state-performance-by-indicator",
        "out": Path("data/raw/az/sped_sppapr"),
        "flat": False,
    },
}

FILE_RE = re.compile(r"\.(xlsx?|csv|zip|pdf|accdb|docx?|pptx?)(\?|$)", re.I)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

HARVEST_JS = """() => {
    const m = document.querySelector('main') || document.body;
    return [...m.querySelectorAll('a[href]')].map(a => ({
        t: (a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 140),
        h: a.href}));
}"""


def harvest(page, url):
    """{file_url: link_text} for one page. Link text matters - it is the only thing
    that distinguishes handler-style URLs from each other."""
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    files = {}
    for link in page.evaluate(HARVEST_JS):
        if FILE_RE.search(link["h"]):
            files.setdefault(link["h"], link["t"] or Path(link["h"]).name)
    return files


def main():
    wanted = [a for a in sys.argv[1:] if a in SOURCES] or list(SOURCES)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1440, "height": 1200},
                                  locale="en-US")
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()
        harvested = {}
        for name in wanted:
            try:
                harvested[name] = harvest(page, SOURCES[name]["url"])
                print(f"{name:16s} {len(harvested[name]):>4} file links")
            except Exception as e:
                print(f"{name:16s} harvest failed: {str(e)[:70]}")
            time.sleep(2)
        browser.close()

    for name, files in harvested.items():
        if not files:
            continue
        cfg = SOURCES[name]
        print(f"\n=== {name} -> {cfg['out']} ===")
        run("az", [], cfg["out"], extra_files=files, flat=cfg["flat"])


if __name__ == "__main__":
    main()
