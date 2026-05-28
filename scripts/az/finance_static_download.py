from pathlib import Path
from urllib.parse import urlparse, unquote
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import csv
import re
import time

SOURCE_PAGES = [
    "https://www.azed.gov/finance/data-collection-reporting-budget",
    "https://www.azed.gov/finance/local-education-agencies",
]

OUT_DIR = Path("data/raw/az/finance")
OUT_DIR.mkdir(parents=True, exist_ok=True)

FILE_EXTS = (".xlsx", ".xls", ".csv", ".pdf", ".zip", ".mdb", ".accdb")


def is_file_link(url):
    lower = url.lower()
    return (
        lower.endswith(FILE_EXTS)
        or "/sites/default/files/" in lower
        or "getdocumentfile" in lower
    )


def safe_filename(url, suggested=None):
    if suggested:
        name = suggested
    else:
        parsed = urlparse(url)
        name = Path(parsed.path).name or "downloaded_file"

    name = unquote(name)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)

    if len(name) > 180:
        stem = Path(name).stem[:140]
        suffix = Path(name).suffix
        name = stem + suffix

    return name


def category_from_text(text, url):
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


def try_download_event(page, url, out_dir):
    page.evaluate(
        """
        url => {
            const old = document.getElementById("temp-download-link");
            if (old) old.remove();

            const a = document.createElement("a");
            a.href = url;
            a.id = "temp-download-link";
            a.textContent = "temp-download-link";
            document.body.appendChild(a);
        }
        """,
        url,
    )

    try:
        with page.expect_download(timeout=12000) as download_info:
            page.click("#temp-download-link")

        download = download_info.value
        filename = safe_filename(url, download.suggested_filename)
        output_path = out_dir / filename
        download.save_as(output_path)

        return output_path, "download_event"

    except PlaywrightTimeoutError:
        return None, "no_download_event"

    finally:
        page.evaluate(
            """
            () => {
                const a = document.getElementById("temp-download-link");
                if (a) a.remove();
            }
            """
        )


def try_save_inline_response(context, url, out_dir):
    temp = context.new_page()

    try:
        response = temp.goto(url, wait_until="domcontentloaded", timeout=60000)

        if response is None:
            return None, "no_response"

        if not response.ok:
            return None, f"http_{response.status}"

        content_type = response.headers.get("content-type", "").lower()

        if (
            any(x in content_type for x in [
                "pdf",
                "spreadsheet",
                "excel",
                "zip",
                "octet-stream",
                "ms-access",
            ])
            or is_file_link(url)
        ):
            filename = safe_filename(url)
            output_path = out_dir / filename
            output_path.write_bytes(response.body())
            return output_path, "response_body"

        return None, f"non_file_content_type:{content_type}"

    finally:
        temp.close()


def main():
    manifest = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        context = browser.new_context(
            accept_downloads=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        for source_page in SOURCE_PAGES:
            print(f"\nOpening {source_page}")
            page.goto(source_page, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            links = page.eval_on_selector_all(
                "a[href]",
                """
                els => els.map(a => ({
                    text: a.innerText.trim(),
                    href: a.href
                }))
                """,
            )

            file_links = []
            for item in links:
                href = item["href"]
                if href not in seen and is_file_link(href):
                    file_links.append(item)
                    seen.add(href)

            print(f"Found {len(file_links)} finance file links")

            for i, item in enumerate(file_links, start=1):
                url = item["href"]
                text = item["text"]
                category = category_from_text(text, url)
                category_dir = OUT_DIR / category
                category_dir.mkdir(parents=True, exist_ok=True)

                print(f"[{i}/{len(file_links)}] {text[:80]} -> {url}")

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
                })

                time.sleep(1)

        browser.close()

    manifest_path = OUT_DIR / "finance_static_manifest.csv"
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "source_page",
                "link_text",
                "url",
                "category",
                "method",
                "saved_path",
            ],
        )
        writer.writeheader()
        writer.writerows(manifest)

    print(f"\nDone. Manifest saved to {manifest_path}")


if __name__ == "__main__":
    main()