"""
Arizona finance files published as static downloads on azed.gov.

Covers the budget/reporting and LEA-list pages: annual financial reports (SAFR),
audit reports, LEA directories and assorted per-year finance workbooks. The dynamic
budget portal is a separate script (finance_dynamic_download.py).

Playwright rather than requests, because several links are handler URLs that only
resolve with a browser session.

    python scripts/az/finance_static_download.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time

import tqdm
from playwright.sync_api import sync_playwright

from common.file_utils import FILE_EXTS, safe_filename, sha256_file
from common.manifest import write_csv
from common.playwright_capture import new_browser_context, try_download_event, try_save_inline_response

SOURCE_PAGES = [
    "https://www.azed.gov/finance/data-collection-reporting-budget",
    "https://www.azed.gov/finance/local-education-agencies",
]

OUT_DIR = Path("data/raw/az/finance")
MANIFEST_PATH = OUT_DIR / "finance_static_manifest.csv"

MANIFEST_FIELDS = ["source_page", "link_text", "url", "category", "method", "saved_path", "size_bytes", "sha256"]


def _is_file_link(url):
    lower = url.lower()
    return (
        lower.endswith(FILE_EXTS)
        or "/sites/default/files/" in lower
        or "getdocumentfile" in lower
    )


def _category_from_text(text, url):
    combined = f"{text} {url}".lower()
    if "safr" in combined or "superintendent" in combined or "annual report" in combined:
        return "safr_superintendent_reports"
    if "audit" in combined or "compliance" in combined:
        return "audit_reports"
    if "active lea" in combined or "fundable" in combined:
        return "lea_lists"
    if "budget" in combined:
        return "budget"
    if "financial" in combined:
        return "financial_reports"
    return "other_finance"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = []
    seen = set()

    with sync_playwright() as p:
        browser, context = new_browser_context(p)
        page = context.new_page()

        for source_page in SOURCE_PAGES:
            print(f"\nOpening {source_page}")
            page.goto(source_page, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            raw_links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(a => ({text: a.innerText.trim(), href: a.href}))",
            )

            file_links = [
                item for item in raw_links
                if item["href"] not in seen and _is_file_link(item["href"])
            ]
            for item in file_links:
                seen.add(item["href"])

            print(f"Found {len(file_links)} finance file links")

            for item in tqdm.tqdm(file_links, desc=source_page.split("/")[-1]):
                url = item["href"]
                text = item["text"]
                category = _category_from_text(text, url)
                category_dir = OUT_DIR / category
                category_dir.mkdir(parents=True, exist_ok=True)

                filename = safe_filename(Path(url).name or text or url)
                dest = category_dir / filename

                if dest.exists() and dest.stat().st_size > 0:
                    manifest.append({
                        "source_page": source_page,
                        "link_text": text,
                        "url": url,
                        "category": category,
                        "method": "skipped_existing",
                        "saved_path": str(dest),
                        "size_bytes": dest.stat().st_size,
                        "sha256": sha256_file(dest),
                    })
                    continue

                output_path, method = try_download_event(page, url, category_dir)
                if output_path is None:
                    output_path, method = try_save_inline_response(context, url, category_dir)

                manifest.append({
                    "source_page": source_page,
                    "link_text": text,
                    "url": url,
                    "category": category,
                    "method": method,
                    "saved_path": str(output_path) if output_path else "",
                    "size_bytes": output_path.stat().st_size if output_path else "",
                    "sha256": sha256_file(output_path) if output_path else "",
                })

                time.sleep(1)

        browser.close()

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    print(f"\nDone. Manifest saved to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
