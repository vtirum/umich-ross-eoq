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
