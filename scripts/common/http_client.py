import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 education-data-pipeline/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def make_session(headers=None):
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
    session.headers.update(headers or _DEFAULT_HEADERS)
    return session
