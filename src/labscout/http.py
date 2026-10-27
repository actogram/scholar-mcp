"""One HTTP client for all sources: polite per-host pacing, retries on busy servers, and an optional disk cache."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .config import Settings

log = logging.getLogger(__name__)

# Seconds between two requests to the same host. NCBI allows 3 requests per second without an API key and 10 with one;
# ROR about 2,000 per 5 minutes; NIH RePORTER asks for no more than one request per second.
PACE = {
    "eutils.ncbi.nlm.nih.gov": 0.34,
    "api.ror.org": 0.16,
    "www.ebi.ac.uk": 0.1,
    "api.reporter.nih.gov": 1.0,
    "clinicaltrials.gov": 0.2,
    "gtr.ukri.org": 0.3,
}
RETRY_STATUS = {429, 500, 502, 503, 504}
CACHE_DAYS = 7

# The earliest moment the next request to a host may start, shared by every client in this process: searches running
# side by side (on the web page and from assistants) share a source's limit instead of each using it in full.
_NEXT: dict[str, float] = {}
_NEXT_LOCK = threading.Lock()


class Http:
    def __init__(
        self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None, pace: bool = True
    ) -> None:
        self.settings = settings or Settings.from_env()
        self._client = httpx.Client(
            timeout=self.settings.timeout,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": self.settings.user_agent},
        )
        self._pace = dict(PACE) if pace else {}
        if pace and self.settings.ncbi_api_key:
            self._pace["eutils.ncbi.nlm.nih.gov"] = 0.11

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Http:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- public helpers ---------------------------------------------------------------------------------------------
    def get_json(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
        return self._request("GET", url, params=params, headers=headers, kind="json")

    def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        return self._request("GET", url, params=params, kind="text")

    def post_form_text(self, url: str, data: dict[str, Any]) -> str:
        return self._request("POST", url, data=data, kind="text")

    def post_json(self, url: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", url, json_body=payload, kind="json")

    # ---- internals --------------------------------------------------------------------------------------------------
    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        kind: str,
    ) -> Any:
        key = self._key(method, url, params, data, json_body, headers)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        host = urlsplit(url).hostname or ""
        delay = 1.0
        for attempt in range(4):
            self._wait(host)
            try:
                resp = self._client.request(method, url, params=params, data=data, json=json_body, headers=headers)
            except httpx.TransportError as err:
                if attempt == 3:
                    raise
                log.warning("network problem with %s (%s), retrying", host, err)
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code in RETRY_STATUS and attempt < 3:
                wait = _retry_after(resp) or delay
                log.warning("%s answered %s, retrying in %.1f s", host, resp.status_code, wait)
                time.sleep(wait)
                delay *= 2
                continue
            resp.raise_for_status()
            value = resp.json() if kind == "json" else resp.text
            self._cache_put(key, value)
            return value
        raise RuntimeError(f"no answer from {host}")  # not reached: the last attempt returns or raises

    def _wait(self, host: str) -> None:
        gap = self._pace.get(host, 0.0)
        if not gap:
            return
        with _NEXT_LOCK:
            now = time.monotonic()
            start = max(now, _NEXT.get(host, 0.0))
            _NEXT[host] = start + gap
        if start > now:
            time.sleep(start - now)

    @staticmethod
    def _key(method: str, url: str, params: Any, data: Any, json_body: Any, headers: Any = None) -> str:
        raw = json.dumps([method, url, params, data, json_body, headers], sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_path(self, key: str) -> Path | None:
        if not self.settings.cache_dir:
            return None
        return self.settings.cache_dir / key[:2] / f"{key}.json"

    def _cache_get(self, key: str) -> Any:
        path = self._cache_path(key)
        if not path or not path.exists():
            return None
        if time.time() - path.stat().st_mtime > CACHE_DAYS * 86400:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["value"]
        except (OSError, ValueError, KeyError):
            return None

    def _cache_put(self, key: str, value: Any) -> None:
        path = self._cache_path(key)
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"value": value}), encoding="utf-8")
            tmp.replace(path)
        except OSError as err:  # a read-only disk only costs speed
            log.debug("cache write skipped: %s", err)


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if value and value.isdigit():
        return min(float(value), 30.0)
    return None
