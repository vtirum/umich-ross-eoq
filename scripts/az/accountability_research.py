from playwright.sync_api import sync_playwright
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
import re


url = "https://www.azed.gov/accountability-research/data"
OUT_DIR = Path("downloads/az/accountability_research")
OUT_DIR.mkdir(parents=True, exist_ok=True)
FILE_EXTS = (".xlsx", ".xls", ".csv", ".pdf", ".zip", ".ppt", ".pptx")


def filename_from_headers_or_url(response, link):
    content_disposition = response.headers.get("content-disposition", "")

    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition)
    if match:
        return unquote(match.group(1)).replace("/", "_")

    parsed = urlparse(link)
    name = Path(parsed.path).name

    if name:
        return unquote(name).replace("/", "_")

    if "GetDocumentFile" in link:
        qs = parse_qs(parsed.query)
        doc_id = qs.get("id", ["unknown"])[0]
        return f"GetDocumentFile_{doc_id}"

    return "downloaded_file"


def try_download_event(page, link):
    page.evaluate(
        """
        url => {
            const a = document.createElement("a");
            a.href = url;
            a.target = "_blank";
            a.rel = "noopener";
            a.textContent = "temp-download-link";
            a.id = "temp-download-link";
            document.body.appendChild(a);
        }
        """,
        link
    )
    try: 
        with page.expect_download(timeout=30000) as download_info:
            page.click("#temp-download-link")

        download = download_info.value
        filename = download.suggested_filename
        # filename = Path(urlparse(link).path).name
        output_path = OUT_DIR / filename
        download.save_as(output_path)

        print(f"Saved: {output_path}")
        return True
    
    except Exception as e:
        print(f"Exception occurred while downloading {link}: {e}")
        return False

    finally:
        page.evaluate(
                """
                () => {
                    const link = document.getElementById("temp-download-link");
                    if (link) {
                        link.remove();
                    }
                }
                """
            )
        
        
def try_save_file(context, link):
    temp_page = context.new_page()
    try: 
        response = temp_page.goto(link, wait_until="networkidle", timeout=60000)
        if response is None:
            print(f"No response from {link}")
            return False
        
        if not response.ok:
            print(f"Failed to load {link}: {response.status} {response.status_text}")
            return False
        
        content_type = response.headers.get("content-type", "").lower()
        
        if (
            "pdf" in content_type
            or "spreadsheet" in content_type
            or "excel" in content_type
            or "zip" in content_type
            or "powerpoint" in content_type
            or "octet-stream" in content_type
            or link.lower().endswith(FILE_EXTS)
            or "getdocumentfile" in link.lower()
        ):
            filename = filename_from_headers_or_url(response, link)
            output_path = OUT_DIR / filename

            output_path.write_bytes(response.body())
            print(f"Saved by response body: {output_path}")

            return True
        
        print(f"Skipped {link} - content type: {content_type}")
        return False
    
    finally:
        temp_page.close()



with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)

    context = browser.new_context(
        accept_downloads=True,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    )

    page = context.new_page()
    #page = browser.new_page()

    page.goto(url, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(5000)

    # print(page.title())
    # print(page.content()[:2000])

    links = page.eval_on_selector_all(
        "a[href]",
        "els => els.map(a => a.href)"
    )

    file_links = []

    for link in links:
        if link.lower().endswith(FILE_EXTS) or "GetDocumentFile" in link:
            file_links.append(link)
            print(link)
    print(f"Found {len(file_links)} file links")    

    for link in file_links:
        try: 
            downloaded = try_download_event(page, link)
            if not downloaded:
                try_save_file(context, link)
            
        except Exception as e:
            print(f"Exception occurred while downloading {link}: {e}")
    
    browser.close()

    