"""Polite HTTP client for public data sources.

- Identifies itself honestly (configurable User-Agent); never imitates a browser or works around bot checks.
- Honours robots.txt for every host.
- Rate-limits per host (minimum interval between requests).
- Retries only transient failures (429/5xx/network). A 401/403 is treated as "access refused" and not retried.
- Optional on-disk cache with a TTL so repeated runs don't re-download unchanged pages.
"""

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """Transient failure after retries."""


class AccessDenied(FetchError):
    """The site refused the request (401/403) or robots.txt disallows it. Do not retry or work around."""


class NotFound(FetchError):
    """404 - e.g. no price file for a market holiday."""


@dataclass
class FetchResult:
    url: str
    content: bytes
    fetched_at: datetime
    from_cache: bool


class PoliteHttpClient:
    def __init__(
        self,
        user_agent: str,
        cache_dir: Path | None = None,
        min_interval_seconds: float = 2.0,
        host_intervals: dict[str, float] | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        max_wait_seconds: float = 120.0,
        client: httpx.Client | None = None,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.user_agent = user_agent
        self.cache_dir = cache_dir
        self.min_interval = min_interval_seconds
        self.host_intervals = host_intervals or {}
        self.max_retries = max_retries
        self.max_wait = max_wait_seconds
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._sleep, self._clock = sleep, clock
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ public

    def get(self, url: str, *, ttl_seconds: float | None = None, params: dict | None = None) -> FetchResult:
        full_url = str(httpx.URL(url, params=params)) if params else url
        if ttl_seconds and (cached := self._read_cache(full_url, ttl_seconds)):
            return cached
        if not self._allowed_by_robots(full_url):
            raise AccessDenied(f"robots.txt disallows {full_url}")

        for attempt in range(self.max_retries + 1):
            self._throttle(full_url)
            started = self._clock()
            try:
                resp = self._client.get(full_url, headers={"User-Agent": self.user_agent})
            except httpx.TransportError as e:
                if attempt == self.max_retries:
                    raise FetchError(f"{full_url}: {e}") from e
                self._sleep(2.0 * 2**attempt)
                continue
            logger.debug("fetched", extra={"url": full_url[:200], "status": resp.status_code,
                                           "seconds": round(self._clock() - started, 2)})  # fmt: skip
            if resp.status_code in (401, 403):
                raise AccessDenied(f"{full_url}: HTTP {resp.status_code} (access refused by the site)")
            if resp.status_code == 404:
                raise NotFound(f"{full_url}: HTTP 404")
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    raise FetchError(f"{full_url}: HTTP {resp.status_code} after {attempt + 1} attempts")
                retry_after = resp.headers.get("retry-after", "")
                wait = float(retry_after) if retry_after.isdigit() else 2.0 * 2**attempt
                if wait > self.max_wait:
                    # The site asked us to back off for a long time: respect it by giving up, not by hanging.
                    raise FetchError(f"{full_url}: HTTP {resp.status_code}, site asked to wait {wait:.0f}s")
                logger.warning("backing off", extra={"host": self._host(full_url), "status": resp.status_code,
                                                     "wait_s": wait, "attempt": attempt + 1})  # fmt: skip
                self._sleep(wait)
                continue
            if resp.status_code >= 400:
                raise FetchError(f"{full_url}: HTTP {resp.status_code}")
            result = FetchResult(full_url, resp.content, datetime.now(UTC), from_cache=False)
            if ttl_seconds:
                self._write_cache(result)
            return result
        raise FetchError(f"{full_url}: exhausted retries")  # pragma: no cover

    # ------------------------------------------------------------------ internals

    def _host(self, url: str) -> str:
        return urlsplit(url).netloc.lower()

    def _throttle(self, url: str) -> None:
        host = self._host(url)
        interval = self.host_intervals.get(host, self.min_interval)
        with self._lock:
            last = self._last_request.get(host)
            now = self._clock()
            if last is not None and now - last < interval:
                self._sleep(interval - (now - last))
            self._last_request[host] = self._clock()

    def _allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.netloc.lower()
        if host not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
            try:
                self._throttle(robots_url)
                resp = self._client.get(robots_url, headers={"User-Agent": self.user_agent})
                body = resp.text if resp.status_code == 200 else ""
                if "<html" in body[:500].lower():  # some sites return a web page instead of robots.txt
                    body = ""
                parser.parse(body.splitlines())
            except httpx.TransportError:
                parser = None  # unknown: allow, like a missing robots.txt
            self._robots[host] = parser
        parser = self._robots[host]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / hashlib.sha256(url.encode()).hexdigest()[:40]

    def _read_cache(self, url: str, ttl: float) -> FetchResult | None:
        path = self._cache_path(url)
        if not path or not path.exists():
            return None
        mtime = path.stat().st_mtime
        if time.time() - mtime > ttl:
            return None
        return FetchResult(url, path.read_bytes(), datetime.fromtimestamp(mtime, UTC), from_cache=True)

    def _write_cache(self, result: FetchResult) -> None:
        path = self._cache_path(result.url)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(result.content)
