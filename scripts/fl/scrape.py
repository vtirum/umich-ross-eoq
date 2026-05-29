import csv
import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SOURCE_PAGES = [
    "https://www.fldoe.org/accountability/data-sys/",
    "https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/index.stml",
    "https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/students.stml",
    "https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/staff.stml",
    "https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/school/index.stml",
    "https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/fl-data.stml",
    "https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/archive.stml",
]

OUT_DIR = Path("data/raw/fl/fldoe")
MANIFEST_PATH = OUT_DIR / "fldoe_manifest.csv"
FAILED_PATH = OUT_DIR / "fldoe_failed.csv"

FILE_EXTS = (
    ".xlsx", ".xls", ".csv", ".pdf", ".zip",
    ".doc", ".docx", ".ppt", ".pptx"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 education-data-pipeline/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def make_session():
    session = requests.Session()

    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(HEADERS)

    return session


def safe_filename(text):
    text = unquote(text)
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text[:180] or "downloaded_file"


def is_file_url(url):
    path = urlparse(url).path.lower()
    return path.endswith(FILE_EXTS)


def category_from_page_or_text(source_page, link_text, file_url):
    combined = f"{source_page} {link_text} {file_url}".lower()

    if "student" in combined or "graduation" in combined or "enrollment" in combined:
        return "students"
    if "staff" in combined or "teacher" in combined or "salary" in combined:
        return "staff_teacher"
    if "school" in combined:
        return "school"
    if "assessment" in combined or "test" in combined or "sat" in combined or "act" in combined or "ap" in combined:
        return "assessment"
    if "discipline" in combined or "suspension" in combined:
        return "discipline"
    if "finance" in combined or "financial" in combined or "funding" in combined:
        return "finance"
    if "archive" in combined or "historical" in combined:
        return "archive"

    return "other"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def get_links_from_page(session, page_url):
    response = session.get(page_url, timeout=60)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    links = []
    for a in soup.select("a[href]"):
        href = urljoin(page_url, a["href"])
        text = " ".join(a.get_text(" ", strip=True).split())

        links.append({
            "source_page": page_url,
            "link_text": text,
            "url": href,
        })

    return links


def download_file(session, item):
    url = item["url"]
    source_page = item["source_page"]
    link_text = item["link_text"]

    category = category_from_page_or_text(source_page, link_text, url)
    category_dir = OUT_DIR / category
    category_dir.mkdir(parents=True, exist_ok=True)

    parsed = urlparse(url)
    filename = Path(parsed.path).name

    if not filename:
        filename = safe_filename(link_text)

    filename = safe_filename(filename)
    output_path = category_dir / filename

    if output_path.exists() and output_path.stat().st_size > 0:
        return {
            "source_page": source_page,
            "link_text": link_text,
            "file_url": url,
            "category": category,
            "local_path": str(output_path),
            "status": "skipped_existing",
            "size_bytes": output_path.stat().st_size,
            "sha256": sha256_file(output_path),
        }

    with session.get(url, stream=True, timeout=120) as response:
        status = response.status_code

        if status >= 400:
            return {
                "source_page": source_page,
                "link_text": link_text,
                "file_url": url,
                "category": category,
                "local_path": "",
                "status": f"http_{status}",
                "size_bytes": "",
                "sha256": "",
            }

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return {
        "source_page": source_page,
        "link_text": link_text,
        "file_url": url,
        "category": category,
        "local_path": str(output_path),
        "status": "downloaded",
        "size_bytes": output_path.stat().st_size,
        "sha256": sha256_file(output_path),
    }


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    session = make_session()

    all_links = []
    seen_pages = set()

    # First pass: collect links from seed pages
    for page_url in SOURCE_PAGES:
        print(f"Reading page: {page_url}")

        try:
            links = get_links_from_page(session, page_url)
            all_links.extend(links)
            seen_pages.add(page_url)
        except Exception as e:
            print(f"Failed page {page_url}: {e}")

        time.sleep(0.5)

    # Second pass: follow FLDOE internal report pages one level deeper
    internal_report_pages = []

    for item in all_links:
        href = item["url"]

        if href in seen_pages:
            continue

        if (
            href.startswith("https://www.fldoe.org/accountability/data-sys/")
            and not is_file_url(href)
            and href.endswith((".stml", "/"))
        ):
            internal_report_pages.append(href)
            seen_pages.add(href)

    for page_url in internal_report_pages:
        print(f"Reading subpage: {page_url}")

        try:
            links = get_links_from_page(session, page_url)
            all_links.extend(links)
        except Exception as e:
            print(f"Failed subpage {page_url}: {e}")

        time.sleep(0.5)

    # Keep only direct files
    file_links = []
    seen_files = set()

    for item in all_links:
        url = item["url"]

        if is_file_url(url) and url not in seen_files:
            file_links.append(item)
            seen_files.add(url)

    print(f"Found {len(file_links)} downloadable files")

    manifest = []
    failed = []

    for i, item in enumerate(file_links, start=1):
        print(f"[{i}/{len(file_links)}] {item['link_text'][:80]} -> {item['url']}")

        try:
            row = download_file(session, item)
            manifest.append(row)
        except Exception as e:
            print(f"FAILED {item['url']}: {e}")

            failed.append({
                "source_page": item["source_page"],
                "link_text": item["link_text"],
                "file_url": item["url"],
                "error": repr(e),
            })

        time.sleep(0.5)

    manifest_fields = [
        "source_page",
        "link_text",
        "file_url",
        "category",
        "local_path",
        "status",
        "size_bytes",
        "sha256",
    ]

    failed_fields = [
        "source_page",
        "link_text",
        "file_url",
        "error",
    ]

    write_csv(MANIFEST_PATH, manifest, manifest_fields)
    write_csv(FAILED_PATH, failed, failed_fields)

    print(f"\nDone.")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"Failed: {FAILED_PATH}")


if __name__ == "__main__":
    main()