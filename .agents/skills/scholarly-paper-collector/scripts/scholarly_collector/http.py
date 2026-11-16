from __future__ import annotations

import json
import hashlib
import logging
import socket
import threading
import time
from collections.abc import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .cache import FileCache
from .config import redact, redact_mapping


class SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        old, new = urlparse(request.full_url), urlparse(new_url)
        if new.scheme != 'https' or new.netloc != old.netloc:
            raise RuntimeError('API redirect to a different host was refused')
        return super().redirect_request(request, response, code, message, headers, new_url)


urlopen = build_opener(SameHostRedirect()).open


_THROTTLE_LOCK = threading.Lock()
_LAST_REQUESTS = {}


class HTTPClient:
    def __init__(self, cache: FileCache, logger: logging.Logger, timeout: int = 30):
        self.cache = cache
        self.logger = logger
        self.timeout = timeout
        self._last_request_at = _LAST_REQUESTS
        self.partial_papers = {}
        self.observations = {}
        self.requests = []

    def throttle(self, bucket: str, seconds: float) -> None:
        with _THROTTLE_LOCK:
            last = self._last_request_at.get(bucket, 0.0)
            wait = seconds - (time.time() - last)
            if wait > 0:
                self.logger.info("throttle bucket=%s wait=%.2fs", bucket, wait)
                time.sleep(wait)
            self._last_request_at[bucket] = time.time()

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        cache_namespace: str = "http",
        retry_delays: Sequence[float] = (1.0, 2.0, 4.0),
        retry_statuses: set[int] | None = None,
        fail_fast_statuses: set[int] | None = None,
    ) -> str:
        retry_statuses = retry_statuses or {429, 500, 502, 503, 504}
        fail_fast_statuses = fail_fast_statuses or set()
        full_url = url
        if params:
            full_url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"
        authorization_scope = hashlib.sha256(json.dumps(headers or {}, sort_keys=True).encode()).hexdigest()
        cache_key = full_url + '#' + authorization_scope
        cached = self.cache.read_text(cache_namespace, cache_key)
        if cached is not None:
            self.logger.info("cache hit url=%s", redact(full_url))
            self.requests.append({'provider': cache_namespace, 'url': redact(full_url), 'cache_hit': True})
            return cached
        clean_headers = redact_mapping(headers)
        self.logger.info("GET url=%s headers=%s", redact(full_url), clean_headers)
        last_error: Exception | None = None
        max_attempts = len(retry_delays) + 1
        for attempt in range(max_attempts):
            try:
                host = urlparse(url).hostname
                interval = 3.0 if host == 'export.arxiv.org' else (1.1 if headers and headers.get('x-api-key') else 5.0) if host == 'api.semanticscholar.org' else 1.0
                self.throttle(host, interval)
                req = Request(full_url, headers=headers or {})
                with urlopen(req, timeout=self.timeout) as response:
                    raw = response.read(12 * 1024 * 1024 + 1)
                    if len(raw) > 12 * 1024 * 1024:
                        raise RuntimeError('API page exceeds 12 MiB')
                    text = raw.decode("utf-8", errors="replace")
                self.requests.append({'provider': cache_namespace, 'url': redact(full_url), 'cache_hit': False, 'status': 200})
                self.cache.write_text(cache_namespace, cache_key, text)
                return text
            except HTTPError as exc:
                last_error = exc
                self.requests.append({'provider': cache_namespace, 'url': redact(full_url), 'status': exc.code})
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    wait_seconds = max(0, float(retry_after or 0))
                except ValueError:
                    wait_seconds = 0
                if exc.code == 429 and (wait_seconds > 60 or (exc.headers and exc.headers.get('X-RateLimit-Remaining-USD') == '0')):
                    raise RuntimeError(f'HTTP 429: quota unavailable; retry after {int(wait_seconds)} seconds') from None
                if exc.code in fail_fast_statuses:
                    raise RuntimeError(f"HTTP {exc.code} from provider; fail-fast policy triggered for {redact(full_url)}")
                if exc.code not in retry_statuses:
                    raise
                self.logger.warning(
                    "retryable HTTP error status=%s attempt=%s/%s retry_after=%s url=%s",
                    exc.code,
                    attempt + 1,
                    max_attempts,
                    retry_after or "",
                    redact(full_url),
                )
            except (URLError, TimeoutError, socket.timeout) as exc:
                last_error = exc
                self.logger.warning("retryable URL error attempt=%s/%s url=%s error=%s", attempt + 1, max_attempts, redact(full_url), redact(exc))
            if attempt < len(retry_delays):
                time.sleep(max(retry_delays[attempt], wait_seconds if isinstance(last_error, HTTPError) else 0))
        raise RuntimeError(f"GET failed after retries: {redact(full_url)} ({redact(last_error)})")

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        cache_namespace: str = "http",
        retry_delays: Sequence[float] = (1.0, 2.0, 4.0),
        retry_statuses: set[int] | None = None,
        fail_fast_statuses: set[int] | None = None,
    ) -> object:
        return json.loads(
            self.get_text(
                url,
                params=params,
                headers=headers,
                cache_namespace=cache_namespace,
                retry_delays=retry_delays,
                retry_statuses=retry_statuses,
                fail_fast_statuses=fail_fast_statuses,
            )
        )
