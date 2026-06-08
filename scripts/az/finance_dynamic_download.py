"""
finance_dynamic_download.py — Automated download from AZ dynamic finance portals.

Runs four automated strategies per page, in order:
  1. Direct file links  — harvests <a href="*.xlsx|pdf|..."> and downloads via requests
  2. Download buttons   — clicks buttons/links whose text matches download keywords
  3. Select enumeration — for each <select>, tries every <option>, clicks Apply/Submit,
                          and captures any resulting file download or network response
  4. Entity list        — for pages like EntitySelection.asp, selects each radio-button
                          entity, clicks Go!, harvests the resulting page, then goes back

Network responses matching file content-types are captured throughout.
No user interaction required.
"""

import sys
import re
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from common.file_utils import FILE_EXTS, safe_filename
from common.http_client import make_session
from common.manifest import write_csv
from common.playwright_capture import new_browser_context

PAGES = [
    "https://budgetsystem.azed.gov/reports/submissionstatusview",
    "https://financesystemprdaps.azurewebsites.net/reports/FSReports",
    "https://budgetsystem.azed.gov/leadocumentsubmission/auditpdfuploadedfiles",
    "https://sfbudget.ade.az.gov/Budget/EntitySelection.asp",
]

OUT_DIR = Path("data/raw/az/finance_dynamic")

# Cap on options enumerated per select/entity list to avoid runaway loops
MAX_SELECT_OPTIONS = 50
MAX_ENTITY_OPTIONS = 200

FILE_CONTENT_TYPES = [
    "application/json", "application/pdf", "spreadsheet",
    "excel", "csv", "zip", "octet-stream",
]

DOWNLOAD_KEYWORDS = re.compile(
    r"download|export|generate report|get report", re.IGNORECASE
)
SUBMIT_KEYWORDS = re.compile(
    r"apply|submit|go!|go|view|generate|search", re.IGNORECASE
)

MANIFEST_FIELDS = ["source_page", "url", "status", "content_type", "saved_path", "method"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_name(text, max_len=120):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)[:max_len]


def _ext_for(content_type, url):
    ct = content_type.lower()
    if "json" in ct or "/api/" in url.lower():
        return ".json"
    if "pdf" in ct:
        return ".pdf"
    if "excel" in ct or "spreadsheet" in ct:
        return ".xlsx"
    if "csv" in ct:
        return ".csv"
    if "zip" in ct:
        return ".zip"
    return ".bin"


def _should_capture(response):
    ct = response.headers.get("content-type", "").lower()
    url = response.url.lower()
    return (
        any(t in ct for t in FILE_CONTENT_TYPES)
        or any(url.endswith(ext) for ext in FILE_EXTS)
        or "/api/" in url
    )


def _save_response(response, out_dir, manifest, source_url, method="net_capture"):
    url = response.url
    ct = response.headers.get("content-type", "")
    try:
        body = response.body()
        if len(body) < 100:
            return
        base = _safe_name(urlparse(url).netloc + urlparse(url).path)
        ext = _ext_for(ct, url)
        out = out_dir / f"{base}{ext}"
        if out.exists():
            out = out_dir / f"{base}_{abs(hash(url)) % 9999}{ext}"
        out.write_bytes(body)
        print(f"  [{method}] {out.name}")
        manifest.append({
            "source_page": source_url,
            "url": url,
            "status": response.status,
            "content_type": ct,
            "saved_path": str(out),
            "method": method,
        })
    except Exception as e:
        print(f"  [net] could not save {url}: {e}")


def _make_capture_handler(out_dir, manifest, source_url):
    def handler(response):
        if _should_capture(response):
            _save_response(response, out_dir, manifest, source_url)
    return handler


# ---------------------------------------------------------------------------
# Strategy 1 — direct file links downloaded via requests
# ---------------------------------------------------------------------------

def _strategy_direct_links(page, out_dir, manifest, source_url, session):
    try:
        items = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(a => ({href: a.href, text: a.innerText.trim()}))",
        )
    except Exception:
        return

    file_items = [i for i in items if i["href"].lower().endswith(FILE_EXTS)]
    if not file_items:
        return
    print(f"  [links] {len(file_items)} direct file link(s)")

    for item in file_items:
        url = item["href"]
        try:
            resp = session.get(url, stream=True, timeout=30)
            if resp.status_code >= 400:
                continue
            filename = safe_filename(Path(urlparse(url).path).name or _safe_name(url)[-60:])
            out = out_dir / filename
            if not out.exists():
                with open(out, "wb") as f:
                    for chunk in resp.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)
            print(f"  [links] {out.name}")
            manifest.append({
                "source_page": source_url,
                "url": url,
                "status": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
                "saved_path": str(out),
                "method": "direct_link",
            })
        except Exception as e:
            print(f"  [links] {url}: {e}")


# ---------------------------------------------------------------------------
# Strategy 2 — click download / export buttons
# ---------------------------------------------------------------------------

def _try_click(locator, page, out_dir, manifest, source_url):
    """Click a locator and capture any resulting download."""
    try:
        count = locator.count()
    except Exception:
        return
    for i in range(min(count, 5)):
        try:
            with page.expect_download(timeout=5000) as dl:
                locator.nth(i).click()
            download = dl.value
            filename = safe_filename(download.suggested_filename or "download")
            out = out_dir / filename
            download.save_as(out)
            print(f"  [btn] {out.name}")
            manifest.append({
                "source_page": source_url,
                "url": download.url,
                "status": 200,
                "content_type": "",
                "saved_path": str(out),
                "method": "download_button",
            })
        except PlaywrightTimeoutError:
            pass  # click didn't trigger a file download
        except Exception as e:
            print(f"  [btn] click error: {e}")


def _strategy_download_buttons(page, out_dir, manifest, source_url):
    for role in ("button", "link"):
        try:
            _try_click(
                page.get_by_role(role, name=DOWNLOAD_KEYWORDS),
                page, out_dir, manifest, source_url,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Strategy 3 — enumerate <select> options, click Apply, capture response
# ---------------------------------------------------------------------------

def _strategy_selects(page, out_dir, manifest, source_url, session):
    try:
        selects = page.locator("select").all()
    except Exception:
        return
    if not selects:
        return

    for select in selects:
        try:
            options = select.locator("option").all()
        except Exception:
            continue

        values = []
        for opt in options:
            try:
                val = opt.get_attribute("value") or ""
                if val.strip() and val not in ("", "0", "-1"):
                    values.append(val)
            except Exception:
                pass

        print(f"  [select] {len(values)} option(s) to enumerate")

        for value in values[:MAX_SELECT_OPTIONS]:
            try:
                select.select_option(value=value)
                page.wait_for_timeout(300)

                # Try each submit-like button; stop at the first download that fires
                for role in ("button", "link"):
                    try:
                        submit = page.get_by_role(role, name=SUBMIT_KEYWORDS)
                        count = submit.count()
                        for i in range(min(count, 3)):
                            try:
                                with page.expect_download(timeout=5000) as dl:
                                    submit.nth(i).click()
                                download = dl.value
                                filename = safe_filename(
                                    download.suggested_filename or f"report_{value}"
                                )
                                out = out_dir / filename
                                download.save_as(out)
                                print(f"  [select] {out.name}")
                                manifest.append({
                                    "source_page": source_url,
                                    "url": download.url,
                                    "status": 200,
                                    "content_type": "",
                                    "saved_path": str(out),
                                    "method": "select_enum",
                                })
                                break
                            except PlaywrightTimeoutError:
                                pass
                    except Exception:
                        pass

                # Let network capture pick up any API responses that fired
                try:
                    page.wait_for_load_state("networkidle", timeout=4000)
                except PlaywrightTimeoutError:
                    pass

            except Exception as e:
                print(f"  [select] option {value}: {e}")

            # After navigating away, go back and restore page state
            try:
                if page.url != source_url:
                    page.go_back(wait_until="networkidle", timeout=8000)
                    page.wait_for_timeout(500)
                    # Re-acquire the select after navigation
                    selects = page.locator("select").all()
                    break  # restart outer loop with fresh selects
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Strategy 4 — entity list (radio buttons + "Go!" button)
# ---------------------------------------------------------------------------

def _strategy_entity_list(page, context, out_dir, manifest, source_url, session):
    """
    For pages like EntitySelection.asp that show a radio-button list of entities
    with a Go!/Submit button. Selects each entity, clicks Go!, harvests the
    resulting page for file links, then navigates back.
    """
    try:
        radios = page.locator("input[type='radio']").all()
    except Exception:
        return
    if not radios:
        return

    print(f"  [entity] {len(radios)} radio option(s)")

    for radio in radios[:MAX_ENTITY_OPTIONS]:
        try:
            value = radio.get_attribute("value") or ""
            label_text = value  # fallback label

            # Click the radio button
            radio.click()
            page.wait_for_timeout(200)

            # Click "Go!" or equivalent submit button
            submitted = False
            for role in ("button", "link"):
                try:
                    go_btn = page.get_by_role(role, name=re.compile(r"go", re.IGNORECASE))
                    if go_btn.count() > 0:
                        go_btn.first.click()
                        submitted = True
                        break
                except Exception:
                    pass

            # Also try input[type=submit] and input[type=button]
            if not submitted:
                for sel in ("input[type='submit']", "input[type='button']", "button[type='submit']"):
                    try:
                        btn = page.locator(sel).first
                        if btn.count() > 0:
                            btn.click()
                            submitted = True
                            break
                    except Exception:
                        pass

            if not submitted:
                continue

            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(500)

            # Harvest file links from the resulting entity page
            entity_out = out_dir / _safe_name(label_text or value)[:60]
            entity_out.mkdir(parents=True, exist_ok=True)
            _strategy_direct_links(page, entity_out, manifest, page.url, session)
            _strategy_download_buttons(page, entity_out, manifest, page.url)

            # Navigate back to selection page
            page.goto(source_url, wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(500)

            # Re-acquire radio list after navigation
            radios = page.locator("input[type='radio']").all()

        except Exception as e:
            print(f"  [entity] {value}: {e}")
            try:
                page.goto(source_url, wait_until="networkidle", timeout=15000)
                radios = page.locator("input[type='radio']").all()
            except Exception:
                break


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _process_page(source_url, context, out_dir, manifest, session):
    page = context.new_page()
    handler = _make_capture_handler(out_dir, manifest, source_url)
    page.on("response", handler)

    print(f"\n{'='*60}\nProcessing: {source_url}")

    try:
        page.goto(source_url, wait_until="networkidle", timeout=30000)
    except PlaywrightTimeoutError:
        print("  Page load timed out — proceeding with partial load")
    page.wait_for_timeout(1500)

    _strategy_direct_links(page, out_dir, manifest, source_url, session)
    _strategy_download_buttons(page, out_dir, manifest, source_url)
    _strategy_selects(page, out_dir, manifest, source_url, session)
    _strategy_entity_list(page, context, out_dir, manifest, source_url, session)

    # Final settle
    try:
        page.wait_for_load_state("networkidle", timeout=4000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1500)
    page.close()


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    session = make_session()

    with sync_playwright() as p:
        browser, context = new_browser_context(p, headless=False)

        for source_url in PAGES:
            parsed = urlparse(source_url)
            page_dir = OUT_DIR / _safe_name(parsed.netloc + parsed.path)[:60]
            page_dir.mkdir(parents=True, exist_ok=True)
            _process_page(source_url, context, page_dir, manifest, session)

        browser.close()

    manifest_path = OUT_DIR / "dynamic_capture_manifest.csv"
    write_csv(manifest_path, manifest, MANIFEST_FIELDS)
    print(f"\nDone. {len(manifest)} file(s) captured. Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
