import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from urllib.parse import urlparse

import tqdm
from playwright.sync_api import sync_playwright

from common.file_utils import FILE_EXTS, safe_filename, sha256_file
from common.manifest import write_csv
from common.playwright_capture import new_browser_context, try_download_event, try_save_inline_response

URL = "https://www.azed.gov/accountability-research/data"
OUT_DIR = Path("data/raw/az/accountability_research")

MANIFEST_FIELDS = ["source_page", "link_text", "file_url", "local_path", "status", "size_bytes", "sha256"]
FAILED_FIELDS = ["source_page", "link_text", "file_url", "error"]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = []
    failed = []

    with sync_playwright() as p:
        browser, context = new_browser_context(p)
        page = context.new_page()

        page.goto(URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(5000)

        raw_links = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(a => ({href: a.href, text: a.innerText.trim()}))",
        )

        file_links = []
        seen = set()
        for item in raw_links:
            href = item["href"]
            if (href.lower().endswith(FILE_EXTS) or "GetDocumentFile" in href) and href not in seen:
                file_links.append(item)
                seen.add(href)

        print(f"Found {len(file_links)} downloadable links")

        for item in tqdm.tqdm(file_links, desc="Downloading"):
            url = item["href"]
            text = item["text"]

            filename = safe_filename(Path(urlparse(url).path).name or text or url)
            dest = OUT_DIR / filename

            if dest.exists() and dest.stat().st_size > 0:
                manifest.append({
                    "source_page": URL,
                    "link_text": text,
                    "file_url": url,
                    "local_path": str(dest),
                    "status": "skipped_existing",
                    "size_bytes": dest.stat().st_size,
                    "sha256": sha256_file(dest),
                })
                continue

            try:
                output_path, method = try_download_event(page, url, OUT_DIR)
                if output_path is None:
                    output_path, method = try_save_inline_response(context, url, OUT_DIR)

                if output_path and output_path.exists():
                    manifest.append({
                        "source_page": URL,
                        "link_text": text,
                        "file_url": url,
                        "local_path": str(output_path),
                        "status": f"downloaded:{method}",
                        "size_bytes": output_path.stat().st_size,
                        "sha256": sha256_file(output_path),
                    })
                else:
                    manifest.append({
                        "source_page": URL,
                        "link_text": text,
                        "file_url": url,
                        "local_path": "",
                        "status": f"failed:{method}",
                        "size_bytes": "",
                        "sha256": "",
                    })
                    failed.append({
                        "source_page": URL,
                        "link_text": text,
                        "file_url": url,
                        "error": method,
                    })

            except Exception as e:
                tqdm.tqdm.write(f"FAILED {url}: {e}")
                manifest.append({
                    "source_page": URL,
                    "link_text": text,
                    "file_url": url,
                    "local_path": "",
                    "status": "exception",
                    "size_bytes": "",
                    "sha256": "",
                })
                failed.append({
                    "source_page": URL,
                    "link_text": text,
                    "file_url": url,
                    "error": repr(e),
                })

        browser.close()

    write_csv(OUT_DIR / "manifest.csv", manifest, MANIFEST_FIELDS)
    write_csv(OUT_DIR / "failed.csv", failed, FAILED_FIELDS)
    print(f"\nDone. {len(manifest)} files tracked, {len(failed)} failed.")


if __name__ == "__main__":
    main()
