from __future__ import annotations

import httpx

from langchain_quanticdata import RobotsChecker, parse_robots

from .helpers import robots

ROBOTS = """
# comment
User-agent: *
Disallow: /private/
Disallow: /*.pdf$
Allow: /private/public-page

User-agent: ExampleBot
Disallow: /
"""


def test_star_group() -> None:
    rules = parse_robots(ROBOTS)
    assert rules.allowed("https://example.com/")
    assert rules.allowed("https://example.com/docs/page")
    assert not rules.allowed("https://example.com/private/x")
    assert rules.allowed("https://example.com/private/public-page")  # longer allow wins
    assert not rules.allowed("https://example.com/files/report.pdf")
    assert rules.allowed("https://example.com/files/report.pdf?download=1")  # $ anchors the end
    assert rules.allowed("https://example.com/robots.txt")


def test_specific_group_wins() -> None:
    rules = parse_robots(ROBOTS, "ExampleBot/1.0")
    assert not rules.allowed("https://example.com/")


def test_empty_disallow_allows_everything() -> None:
    assert parse_robots("User-agent: *\nDisallow:\n").allowed("https://example.com/a")


def test_disallowed_paths() -> None:
    assert parse_robots(ROBOTS).disallowed_paths() == ["/private/", "/*.pdf$"]


def test_status_handling() -> None:
    checker = robots({"gone.example": 404, "down.example": 503})
    assert checker.allowed("https://gone.example/page")
    assert not checker.allowed("https://down.example/page")


def test_network_error_disallows() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    checker = RobotsChecker(transport=httpx.MockTransport(boom))
    assert not checker.allowed("https://unreachable.example/")


def test_cache_per_origin() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /x\n")

    checker = RobotsChecker(transport=httpx.MockTransport(handler))
    assert checker.allowed("https://example.com/a")
    assert not checker.allowed("https://example.com/x/1")
    assert calls == ["https://example.com/robots.txt"]


async def test_async_checker() -> None:
    checker = robots({"example.com": "User-agent: *\nDisallow: /x\n"})
    assert await checker.aallowed("https://example.com/a")
    assert not await checker.aallowed("https://example.com/x")
