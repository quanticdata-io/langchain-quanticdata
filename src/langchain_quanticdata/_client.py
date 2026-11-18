"""Minimal sync and async HTTP client for the documented QuanticData endpoints this package uses.

Every call sends ``Authorization: Bearer <key>`` to ``base_url`` and unwraps the success
envelope ``{"type": "response", "message": ..., "payload": {...}}``. Errors answer
``{"type": "error", "message": ..., "payload"?: {...}}`` and are raised as
:class:`QuanticDataAPIError`. API reference: https://quanticdata.io/docs/
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping
from typing import Any

import httpx

from ._version import __version__

DEFAULT_BASE_URL = "https://api.quanticdata.io/v1"
API_KEY_ENV = "QUANTICDATA_API_KEY"
BASE_URL_ENV = "QUANTICDATA_API_BASE"

#: A 429 is retried only when the server asks to wait at most this long.
MAX_RETRY_AFTER_SECONDS = 30.0


class QuanticDataError(Exception):
    """Base class of the errors raised by this package."""


class QuanticDataAPIError(QuanticDataError):
    """The API answered with an error status.

    ``status`` is the HTTP status, ``message`` the envelope's message and ``payload`` the
    structured detail when the API sent one (for example the code of a 402 or 429).
    """

    def __init__(self, status: int, message: str, payload: Mapping[str, Any] | None = None) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message
        self.payload: dict[str, Any] = dict(payload or {})


class QuanticDataJobError(QuanticDataError):
    """An asynchronous job (crawl or batch) ended as ``failed`` or ``cancelled``, or timed out."""


def resolve_api_key(api_key: str | None) -> str:
    key = api_key or os.environ.get(API_KEY_ENV)
    if not key:
        raise ValueError(
            f"No QuanticData API key: pass api_key=... or set the {API_KEY_ENV} environment variable. "
            "Keys are created on the API keys page of the QuanticData dashboard."
        )
    return key


def resolve_base_url(base_url: str | None) -> str:
    return (base_url or os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if 0 <= seconds <= MAX_RETRY_AFTER_SECONDS else None


def _unwrap(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.is_success and isinstance(body, dict) and isinstance(body.get("payload"), dict):
        payload_: dict[str, Any] = body["payload"]
        return payload_
    if isinstance(body, dict):
        message = str(body.get("message") or response.reason_phrase or "error")
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else None
    else:
        message = response.text[:300] or response.reason_phrase or "error"
        payload = None
    if response.is_success:
        raise QuanticDataAPIError(response.status_code, f"Unexpected response body: {message}")
    raise QuanticDataAPIError(response.status_code, message, payload)


def _clean(body: Mapping[str, Any]) -> dict[str, Any]:
    """Drops ``None`` values so that only the options the caller set are sent."""
    return {k: v for k, v in body.items() if v is not None}


class _Base:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        self.api_key = resolve_api_key(api_key)
        self.base_url = resolve_base_url(base_url)
        self.timeout = timeout
        self.max_retries = max_retries

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": f"langchain-quanticdata/{__version__}",
        }


class QuanticDataClient(_Base):
    """Synchronous client. Pass ``transport`` to route requests elsewhere (tests use
    :class:`httpx.MockTransport`)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(api_key, base_url=base_url, timeout=timeout, max_retries=max_retries)
        self._http = httpx.Client(
            base_url=self.base_url, headers=self._headers(), timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            response = self._http.request(
                method, path, json=_clean(json) if json is not None else None, params=params
            )
            wait = _retry_after(response) if response.status_code == 429 else None
            if wait is not None and attempt < self.max_retries:
                attempt += 1
                time.sleep(wait)
                continue
            return _unwrap(response)

    def search(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/scraper/serp", json=body)

    def scrape(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/scraper/extract", json=body)

    def map(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/scraper/map", json=body)

    def start_crawl(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/scraper/crawl", json=body)

    def get_crawl(self, job_id: str, *, since: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {} if since is None else {"since": since}
        return self.request("GET", f"/scraper/crawl/{job_id}", params=params)

    def start_batch(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/scraper/batch", json=body)

    def get_batch(self, job_id: str, *, since: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"include_content": "true"}
        if since is not None:
            params["since"] = since
        return self.request("GET", f"/scraper/batch/{job_id}", params=params)


class AsyncQuanticDataClient(_Base):
    """Asynchronous twin of :class:`QuanticDataClient`."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(api_key, base_url=base_url, timeout=timeout, max_retries=max_retries)
        self._http = httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers(), timeout=timeout, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            response = await self._http.request(
                method, path, json=_clean(json) if json is not None else None, params=params
            )
            wait = _retry_after(response) if response.status_code == 429 else None
            if wait is not None and attempt < self.max_retries:
                attempt += 1
                await asyncio.sleep(wait)
                continue
            return _unwrap(response)

    async def search(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/scraper/serp", json=body)

    async def scrape(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/scraper/extract", json=body)

    async def map(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/scraper/map", json=body)

    async def start_crawl(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/scraper/crawl", json=body)

    async def get_crawl(self, job_id: str, *, since: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {} if since is None else {"since": since}
        return await self.request("GET", f"/scraper/crawl/{job_id}", params=params)

    async def start_batch(self, body: Mapping[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/scraper/batch", json=body)

    async def get_batch(self, job_id: str, *, since: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"include_content": "true"}
        if since is not None:
            params["since"] = since
        return await self.request("GET", f"/scraper/batch/{job_id}", params=params)
