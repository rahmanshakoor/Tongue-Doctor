"""Shared HTTP + filesystem helpers for ingesters.

Polite, retrying, content-hashed download to disk. No business logic — every
ingester uses the same building blocks so rate-limit and identification policy is
uniform across the corpus.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CONTACT = "rahman@yabagram.com"


def http_client(
    *,
    timeout_s: float = 60.0,
    follow_redirects: bool = True,
    user_agent: str | None = None,
) -> httpx.Client:
    """Build a configured ``httpx.Client``.

    The default User-Agent is browser-like because several sources (NCBI
    Bookshelf among them) 403 on bot-shaped agents even with explicit identification.
    The ``From:`` header carries contact info per RFC 7231 §5.5.1 so administrators
    have a reach-out path if a crawl pattern is unwelcome.
    """

    return httpx.Client(
        headers={
            "User-Agent": user_agent or USER_AGENT,
            "From": CONTACT,
            "Accept": "*/*",
        },
        timeout=httpx.Timeout(timeout_s),
        follow_redirects=follow_redirects,
        http2=False,
    )


@retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.RemoteProtocolError)),
)
def get_with_retry(client: httpx.Client, url: str, **kwargs: object) -> httpx.Response:
    """GET with exponential backoff on transient errors.

    4xx are not retried (those are bugs in our request). Only 5xx + connection
    errors retry, up to 4 attempts.
    """

    response = client.get(url, **kwargs)  # type: ignore[arg-type]
    if 500 <= response.status_code < 600:
        raise httpx.HTTPStatusError(
            f"server {response.status_code} on {url}", request=response.request, response=response
        )
    response.raise_for_status()
    return response


def download_to(client: httpx.Client, url: str, dest: Path, *, chunk_size: int = 1 << 16) -> Path:
    """Stream a URL to ``dest`` if the file is missing, else no-op.

    The caller is responsible for picking a stable filename so caching works across
    re-runs. Raises on HTTP error.
    """

    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with tmp.open("wb") as f:
            for piece in response.iter_bytes(chunk_size):
                f.write(piece)
    tmp.replace(dest)
    return dest


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for piece in iter(lambda: f.read(1 << 16), b""):
            h.update(piece)
    return h.hexdigest()


def polite_iter[T](items: list[T], *, min_interval_s: float) -> Iterator[T]:
    """Yield items, sleeping between to enforce a minimum interval.

    Use for per-request rate-limiting against APIs without a documented quota.
    """

    last = 0.0
    for item in items:
        elapsed = time.time() - last
        if elapsed < min_interval_s:
            time.sleep(min_interval_s - elapsed)
        last = time.time()
        yield item
