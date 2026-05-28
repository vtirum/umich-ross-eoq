from playwright.sync_api import sync_playwright
from pathlib import Path
from urllib.parse import urlparse
import csv
import re
import time

PAGES = [
    "https://budgetsystem.azed.gov/reports/submissionstatusview",
    "https://financesystemprdaps.azurewebsites.net/reports/FSReports",
    "https://budgetsystem.azed.gov/leadocumentsubmission/auditpdfuploadedfiles",
    "https://sfbudget.ade.az.gov/Budget/EntitySelection.asp",
]

OUT_DIR = Path("data/raw/az/finance_dynamic")
OUT_DIR.mkdir(parents=True, exist_ok=True)

FILE_TYPES = [
    "application/json",
    "application/pdf",
    "spreadsheet",
    "excel",
    "csv",
    "zip",
    "octet-stream",
]


def safe_name(text):
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text[:180]


def should_save_response(response):
    url = response.url.lower()
    content_type = response.headers.get("content-type", "").lower()

    if any(t in content_type for t in FILE_TYPES):
        return True

    if any(url.endswith(ext) for ext in [".xlsx", ".xls", ".csv", ".pdf", ".zip"]):
        return True

    if "/api/" in url:
        return True

    return False


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

    manifest = []

    def handle_response(response):
        if not should_save_response(response):
            return

        url = response.url
        status = response.status
        content_type = response.headers.get("content-type", "")

        print(f"CAPTURED {status} {content_type}: {url}")

        try:
            body = response.body()

            parsed = urlparse(url)
            filename_base = safe_name(parsed.netloc + parsed.path)

            if "json" in content_type.lower() or "/api/" in url.lower():
                ext = ".json"
            elif "pdf" in content_type.lower():
                ext = ".pdf"
            elif "excel" in content_type.lower() or "spreadsheet" in content_type.lower():
                ext = ".xlsx"
            elif "csv" in content_type.lower():
                ext = ".csv"
            elif "zip" in content_type.lower():
                ext = ".zip"
            else:
                ext = ".bin"

            output_path = OUT_DIR / f"{filename_base}{ext}"
            output_path.write_bytes(body)

            manifest.append({
                "url": url,
                "status": status,
                "content_type": content_type,
                "saved_path": str(output_path),
            })

        except Exception as e:
            print(f"Could not save response: {e}")

            manifest.append({
                "url": url,
                "status": status,
                "content_type": content_type,
                "saved_path": "",
            })

    context.on("response", handle_response)

    page = context.new_page()

    for url in PAGES:
        print(f"\nOpening {url}")
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        print("Use the browser to select fiscal year / LEA / report filters, then click Apply or Download.")
        input("Press Enter here after you finish interacting with this page...")

    browser.close()

    manifest_path = OUT_DIR / "dynamic_capture_manifest.csv"
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["url", "status", "content_type", "saved_path"],
        )
        writer.writeheader()
        writer.writerows(manifest)

    print(f"Saved manifest to {manifest_path}")