"""
Filename and hashing helpers shared by every downloader.

`safe_filename` is the important one: portal URLs carry percent-encoding, spaces and
punctuation that break on some filesystems, and link text is often the only meaningful
name a file has. `sha256_file` backs the manifests' duplicate detection.
"""

import hashlib
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

FILE_EXTS = (
    ".xlsx", ".xls", ".csv", ".pdf", ".zip",
    ".doc", ".docx", ".ppt", ".pptx", ".mdb", ".accdb",
)


def safe_filename(text, max_len=180):
    text = unquote(str(text))
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    if len(text) > max_len:
        p = Path(text)
        text = p.stem[: max_len - len(p.suffix)] + p.suffix
    return text or "downloaded_file"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_file_url(url):
    return urlparse(url).path.lower().endswith(FILE_EXTS)
