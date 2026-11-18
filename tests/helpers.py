"""Mock QuanticData API and mock websites for the tests. Nothing here touches the network."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from langchain_quanticdata import AsyncQuanticDataClient, QuanticDataClient, RobotsChecker

FIXTURES = Path(__file__).parent / "fixtures"
TEST_KEY = "qd_test_key"
BASE = "https://api.test.invalid/v1"

Responder = dict[str, Any] | httpx.Response | Callable[[httpx.Request], httpx.Response]


def fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def envelope(payload: dict[str, Any], message: str = "OK") -> dict[str, Any]:
    return {"type": "response", "message": message, "payload": payload, "pagination": {}}


def error(status: int, message: str, payload: dict[str, Any] | None = None) -> httpx.Response:
    body: dict[str, Any] = {"type": "error", "message": message}
    if payload is not None:
        body["payload"] = payload
    return httpx.Response(status, json=body)


class MockApi:
    """Routes ``(METHOD, path)`` to queued answers and records every request.

    The last answer of a route is repeated once the queue is down to one entry.
    """

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], list[Responder]] = {}
        self.requests: list[httpx.Request] = []

    def add(self, method: str, path: str, *answers: Responder) -> MockApi:
        self.routes.setdefault((method, path), []).extend(answers)
        return self

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/v1")
        queue = self.routes.get((request.method, path))
        if not queue:
            return error(404, f"No mock for {request.method} {path}")
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(answer):
            return answer(request)
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    async def ahandle(self, request: httpx.Request) -> httpx.Response:
        return self.handle(request)

    def bodies(self, path: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in self.requests:
            if r.url.path.removeprefix("/v1") == path and r.content:
                out.append(json.loads(r.content))
        return out

    def client(self) -> QuanticDataClient:
        return QuanticDataClient(TEST_KEY, base_url=BASE, transport=httpx.MockTransport(self.handle))

    def async_client(self) -> AsyncQuanticDataClient:
        return AsyncQuanticDataClient(TEST_KEY, base_url=BASE, transport=httpx.MockTransport(self.ahandle))


def robots(rules: dict[str, str | int] | None = None, user_agent: str = "*") -> RobotsChecker:
    """A robots.txt checker whose sites answer from ``rules``: host -> robots.txt text, or an
    HTTP status. Hosts not listed answer 404 (no restrictions)."""
    table = rules or {}

    def handler(request: httpx.Request) -> httpx.Response:
        value = table.get(request.url.host, 404)
        if isinstance(value, int):
            return httpx.Response(value, text="")
        return httpx.Response(200, text=value)

    async def ahandler(request: httpx.Request) -> httpx.Response:
        return handler(request)

    return RobotsChecker(
        user_agent,
        transport=httpx.MockTransport(handler),
        async_transport=httpx.MockTransport(ahandler),
    )
