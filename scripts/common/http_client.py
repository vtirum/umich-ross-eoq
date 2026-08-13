"""
Shared requests sessions.

Two flavours, because the right retry policy depends on the server:

  make_session()       patient - retries 5 times with backoff. Fine for ordinary
                       file downloads off a CDN or static host.
  fail_fast_session()  gives up quickly. Use it for long runs against a server
                       that throttles: with the patient policy a single hung
                       connection costs 5+ minutes, and Minnesota's report card
                       degraded from ~1s to ~200s per request that way.

BROWSER_UA is here so the 37 scripts that need to look like a browser stop each
carrying their own copy.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 education-data-pipeline/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

BROWSER_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _build(headers, retry):
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(headers)
    return session


def make_session(headers=None):
    """Patient session: 5 retries with backoff."""
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    return _build(headers or _DEFAULT_HEADERS, retry)


def fail_fast_session(headers=None):
    """One retry, short backoff - for throttling servers and long runs."""
    retry = Retry(
        total=1,
        connect=1,
        read=1,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    return _build(headers or BROWSER_HEADERS, retry)
