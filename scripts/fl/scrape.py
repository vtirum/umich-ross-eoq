"""
Florida DOE static data pages (fldoe.org).

Crawls the accountability and statistics sections and downloads the spreadsheets and
PDFs they link. Akamai blocks some direct file requests, so the bulk EDW files come
via a separate script (fldoe_download.py) that proxies through the Wayback Machine.

    python scripts/fl/scrape.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import random
import time
from urllib.parse import urljoin, urlparse

import tqdm
import requests
from bs4 import BeautifulSoup

from common.file_utils import safe_filename, sha256_file, is_file_url
from common.http_client import make_session
from common.manifest import write_csv

# fldoe.org sits behind an Akamai WAF that 403s obvious bot User-Agents and
# rate-limits aggressive crawling. Use a realistic browser UA + full header set.
FLDOE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Jittered politeness delay (seconds) between requests, to avoid re-triggering
# the WAF rate limiter. Randomized so the cadence isn't an obvious robotic beat.
DELAY_RANGE = (1.5, 3.5)

# If this many consecutive requests are WAF-blocked, abort early rather than
# grinding through dozens of guaranteed failures.
MAX_CONSECUTIVE_BLOCKS = 4


class BlockedError(Exception):
    """Raised when fldoe.org's WAF returns an Access Denied / 403 block page."""


def _polite_sleep():
    time.sleep(random.uniform(*DELAY_RANGE))


def _check_blocked(response):
    """Raise BlockedError if the response looks like an Akamai WAF block."""
    if response.status_code == 403:
        raise BlockedError(f"HTTP 403 for {response.url}")
    # Akamai serves a 200/403 page literally titled "Access Denied"
    head = response.text[:600].lower() if response.text else ""
    if "access denied" in head and "reference" in head:
        raise BlockedError(f"Akamai 'Access Denied' page for {response.url}")

SOURCE_PAGES = [
    # Main data systems
    "https://www.fldoe.org/accountability/data-sys/",
    "https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/index.stml",

    # PK-12 publications
    "https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/students.stml",
    "https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/staff.stml",
    "https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/school/index.stml",
    "https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/fl-data.stml",
    "https://www.fldoe.org/accountability/data-sys/edu-info-accountability-services/pk-12-public-school-data-pubs-reports/archive.stml",

    # Assessments
    "https://www.fldoe.org/accountability/assessments/k-12-student-assessment/results/",

    # Finance
    "https://www.fldoe.org/finance/fl-edu-finance-program-fefp/",

    # Discipline
    "https://www.fldoe.org/safe-schools/discipline-data.stml",

    # School grades / accountability (current + archives)
    "https://www.fldoe.org/accountability/accountability-reporting/school-grades/",
    "https://www.fldoe.org/accountability/accountability-reporting/school-grades/archives.stml",

    # FETPIP — post-graduation employment and earnings outcomes
    "https://www.fldoe.org/accountability/fl-edu-training-placement-info-program/pubs.stml",
    "https://www.fldoe.org/accountability/fl-edu-training-placement-info-program/high-school-reports.stml",
    "https://www.fldoe.org/accountability/fl-edu-training-placement-info-program/workforce-edu-reports.stml",

    # Career & Adult Education / CAPE industry certifications
    "https://www.fldoe.org/academics/career-adult-edu/research-evaluation/data-reports-adult-edu.stml",
    "https://www.fldoe.org/academics/career-adult-edu/research-evaluation/cape-annual-enrollment.stml",
    "https://www.fldoe.org/academics/career-adult-edu/research-evaluation/cape-industry-certification.stml",
    "https://www.fldoe.org/academics/career-adult-edu/research-evaluation/yearly-archived-materials.stml",

    # Florida College System reports and fact books
    "https://www.fldoe.org/accountability/data-sys/CCTCMIS/reports.stml",
]

ALLOWED_PREFIXES = (
    "https://www.fldoe.org/accountability/data-sys/",
    "https://www.fldoe.org/accountability/assessments/",
    "https://www.fldoe.org/accountability/accountability-reporting/",
    "https://www.fldoe.org/accountability/fl-edu-training-placement-info-program/",
    "https://www.fldoe.org/finance/",
    "https://www.fldoe.org/safe-schools/",
    "https://www.fldoe.org/academics/career-adult-edu/",
)

OUT_DIR = Path("data/raw/fl/fldoe")
MANIFEST_PATH = OUT_DIR / "fldoe_manifest.csv"
FAILED_PATH = OUT_DIR / "fldoe_failed.csv"

MANIFEST_FIELDS = ["source_page", "link_text", "file_url", "category", "local_path", "status", "size_bytes", "sha256"]
FAILED_FIELDS = ["source_page", "link_text", "file_url", "error"]


def _category(source_page, link_text, file_url):
    combined = f"{source_page} {link_text} {file_url}".lower()
    if "student" in combined or "graduation" in combined or "enrollment" in combined:
        return "students"
    if "staff" in combined or "teacher" in combined or "salary" in combined:
        return "staff_teacher"
    if "fetpip" in combined or "workforce" in combined or "placement" in combined or "earnings" in combined:
        return "fetpip_outcomes"
    if "cape" in combined or "career" in combined or "cte" in combined or "adult" in combined or "vocation" in combined:
        return "career_adult_education"
    if "college system" in combined or "cctcmis" in combined or " fcs " in combined:
        return "college_system"
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


def _get_links(session, page_url):
    response = session.get(page_url, timeout=60)
    _check_blocked(response)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    links = []
    for a in soup.select("a[href]"):
        href = urljoin(page_url, a["href"])
        text = " ".join(a.get_text(" ", strip=True).split())
        links.append({"source_page": page_url, "link_text": text, "url": href})
    return links


def _download_file(session, item):
    url = item["url"]
    source_page = item["source_page"]
    link_text = item["link_text"]

    category = _category(source_page, link_text, url)
    category_dir = OUT_DIR / category
    category_dir.mkdir(parents=True, exist_ok=True)

    filename = safe_filename(Path(urlparse(url).path).name or link_text)
    output_path = category_dir / filename

    if output_path.exists() and output_path.stat().st_size > 0:
        return {
            "source_page": source_page, "link_text": link_text, "file_url": url,
            "category": category, "local_path": str(output_path),
            "status": "skipped_existing", "size_bytes": output_path.stat().st_size,
            "sha256": sha256_file(output_path),
        }

    with session.get(url, stream=True, timeout=120) as response:
        if response.status_code == 403:
            raise BlockedError(f"HTTP 403 for {url}")
        if response.status_code >= 400:
            return {
                "source_page": source_page, "link_text": link_text, "file_url": url,
                "category": category, "local_path": "",
                "status": f"http_{response.status_code}", "size_bytes": "", "sha256": "",
            }
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return {
        "source_page": source_page, "link_text": link_text, "file_url": url,
        "category": category, "local_path": str(output_path),
        "status": "downloaded", "size_bytes": output_path.stat().st_size,
        "sha256": sha256_file(output_path),
    }


def _abort_if_blocked(consecutive_blocks):
    """Raise SystemExit with guidance once too many consecutive WAF blocks occur."""
    if consecutive_blocks >= MAX_CONSECUTIVE_BLOCKS:
        raise SystemExit(
            f"\nAborting: {consecutive_blocks} consecutive WAF blocks from fldoe.org.\n"
            "This is an Akamai rate-limit / IP block, not a code bug. "
            "Wait (typically minutes to a few hours), then rerun. "
            "Re-running while blocked can extend the block."
        )


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session(headers=FLDOE_HEADERS)

    all_links = []
    seen_pages = set()
    consecutive_blocks = 0

    print("Pass 1: collecting links from seed pages...")
    for page_url in tqdm.tqdm(SOURCE_PAGES, desc="Seed pages"):
        try:
            all_links.extend(_get_links(session, page_url))
            seen_pages.add(page_url)
            consecutive_blocks = 0
        except BlockedError as e:
            consecutive_blocks += 1
            tqdm.tqdm.write(f"WAF blocked: {e}")
            _abort_if_blocked(consecutive_blocks)
        except Exception as e:
            tqdm.tqdm.write(f"Failed page {page_url}: {e}")
        _polite_sleep()

    print("Pass 2: following internal FLDOE subpages one level deeper...")
    subpages = [
        item["url"] for item in all_links
        if item["url"] not in seen_pages
        and item["url"].startswith(ALLOWED_PREFIXES)
        and not is_file_url(item["url"])
        and item["url"].endswith((".stml", "/"))
    ]
    seen_pages.update(subpages)

    for page_url in tqdm.tqdm(subpages, desc="Subpages"):
        try:
            all_links.extend(_get_links(session, page_url))
            consecutive_blocks = 0
        except BlockedError as e:
            consecutive_blocks += 1
            tqdm.tqdm.write(f"WAF blocked: {e}")
            _abort_if_blocked(consecutive_blocks)
        except Exception as e:
            tqdm.tqdm.write(f"Failed subpage {page_url}: {e}")
        _polite_sleep()

    seen_files = set()
    file_links = []
    for item in all_links:
        if is_file_url(item["url"]) and item["url"] not in seen_files:
            file_links.append(item)
            seen_files.add(item["url"])

    print(f"Found {len(file_links)} downloadable files")

    manifest = []
    failed = []

    for item in tqdm.tqdm(file_links, desc="Downloading"):
        try:
            row = _download_file(session, item)
            manifest.append(row)
            consecutive_blocks = 0
        except BlockedError as e:
            consecutive_blocks += 1
            tqdm.tqdm.write(f"WAF blocked: {e}")
            failed.append({
                "source_page": item["source_page"],
                "link_text": item["link_text"],
                "file_url": item["url"],
                "error": repr(e),
            })
            # Flush what we have before aborting, so progress isn't lost
            if consecutive_blocks >= MAX_CONSECUTIVE_BLOCKS:
                write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
                write_csv(FAILED_PATH, failed, FAILED_FIELDS)
            _abort_if_blocked(consecutive_blocks)
        except Exception as e:
            tqdm.tqdm.write(f"FAILED {item['url']}: {e}")
            failed.append({
                "source_page": item["source_page"],
                "link_text": item["link_text"],
                "file_url": item["url"],
                "error": repr(e),
            })
        _polite_sleep()

    write_csv(MANIFEST_PATH, manifest, MANIFEST_FIELDS)
    write_csv(FAILED_PATH, failed, FAILED_FIELDS)
    print(f"\nDone. {len(manifest)} files tracked, {len(failed)} failed.")
    print(f"Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
