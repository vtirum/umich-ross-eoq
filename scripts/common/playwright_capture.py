import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from common.file_utils import FILE_EXTS, safe_filename

PLAYWRIGHT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_DOWNLOAD_CONTENT_TYPES = [
    "pdf", "spreadsheet", "excel", "zip", "octet-stream", "ms-access",
]


def is_headless():
    """Read HEADLESS env var. Set HEADLESS=1 to run without a visible browser."""
    return os.environ.get("HEADLESS", "0") not in ("0", "false", "no", "")


def filename_from_headers_or_url(response, url):
    cd = response.headers.get("content-disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
    if m:
        return unquote(m.group(1)).replace("/", "_")
    name = Path(urlparse(url).path).name
    return unquote(name) if name else "downloaded_file"


def try_download_event(page, url, out_dir, timeout=12000):
    """Inject a temporary <a> tag, click it, and capture the browser download.

    Returns (output_path, method) where method is 'download_event' or 'no_download_event'.
    """
    page.evaluate(
        """
        url => {
            const old = document.getElementById("_edu_dl_link");
            if (old) old.remove();
            const a = document.createElement("a");
            a.href = url;
            a.id = "_edu_dl_link";
            a.textContent = "_edu_dl_link";
            document.body.appendChild(a);
        }
        """,
        url,
    )
    try:
        with page.expect_download(timeout=timeout) as dl:
            page.click("#_edu_dl_link")
        download = dl.value
        filename = safe_filename(download.suggested_filename or url)
        output_path = Path(out_dir) / filename
        download.save_as(output_path)
        return output_path, "download_event"
    except PlaywrightTimeoutError:
        return None, "no_download_event"
    finally:
        page.evaluate(
            """
            () => {
                const a = document.getElementById("_edu_dl_link");
                if (a) a.remove();
            }
            """
        )


def try_save_inline_response(context, url, out_dir):
    """Navigate to a URL in a temp page and save the response body if it is a file.

    Returns (output_path, method).
    """
    temp = context.new_page()
    try:
        response = temp.goto(url, wait_until="domcontentloaded", timeout=60000)
        if response is None:
            return None, "no_response"
        if not response.ok:
            return None, f"http_{response.status}"
        content_type = response.headers.get("content-type", "").lower()
        is_file = (
            any(t in content_type for t in _DOWNLOAD_CONTENT_TYPES)
            or url.lower().endswith(FILE_EXTS)
            or "getdocumentfile" in url.lower()
        )
        if not is_file:
            return None, f"non_file:{content_type}"
        filename = safe_filename(filename_from_headers_or_url(response, url))
        output_path = Path(out_dir) / filename
        output_path.write_bytes(response.body())
        return output_path, "response_body"
    finally:
        temp.close()


def new_browser_context(playwright, headless=None):
    """Launch Chromium and return (browser, context). headless defaults to HEADLESS env var."""
    if headless is None:
        headless = is_headless()
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(
        accept_downloads=True,
        user_agent=PLAYWRIGHT_UA,
    )
    return browser, context
