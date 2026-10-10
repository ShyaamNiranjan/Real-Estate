"""IndexNow pings on publish, update, sold and unpublish (docs/SCOPE.md 8.12). Sent in the
background so a slow search engine never slows down the Studio; failures are only logged."""

import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

from app.config import get_settings

log = logging.getLogger("scrollwalk.indexnow")
ENDPOINT = "https://api.indexnow.org/indexnow"
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="indexnow")

sent: list[list[str]] = []  # what was submitted, for tests and local inspection


def _post(urls: list[str]) -> None:
    settings = get_settings()
    body = {"host": urlparse(settings.site_url).netloc, "key": settings.indexnow_key,
            "keyLocation": f"{settings.site_url}/{settings.indexnow_key}.txt", "urlList": urls}
    try:
        r = httpx.post(ENDPOINT, json=body, timeout=10)
        if r.status_code >= 400:
            log.warning("IndexNow answered %s for %d urls", r.status_code, len(urls))
    except httpx.HTTPError as exc:
        log.warning("IndexNow failed: %s", exc)


def submit(*paths: str) -> None:
    """Paths like `/ana` or `/ana/villa-aurelia`. Does nothing until INDEXNOW_KEY is set."""
    settings = get_settings()
    if not settings.indexnow_key or not paths:
        return
    urls = sorted({f"{settings.site_url}{p}" for p in paths})
    sent.append(urls)
    _pool.submit(_post, urls)
