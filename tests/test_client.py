from __future__ import annotations

import httpx
import pytest

from langchain_quanticdata import QuanticDataAPIError, QuanticDataClient
from langchain_quanticdata._client import DEFAULT_BASE_URL, resolve_base_url

from .helpers import BASE, TEST_KEY, MockApi, envelope, error, fixture


def test_sends_bearer_key_and_unwraps_the_envelope() -> None:
    api = MockApi().add("POST", "/scraper/serp", fixture("serp_bing"))
    payload = api.client().search({"query": "rag", "engine": "bing", "country": None})
    assert payload["organic"][0]["rank"] == 1
    request = api.requests[0]
    assert request.headers["authorization"] == f"Bearer {TEST_KEY}"
    assert str(request.url) == f"{BASE}/scraper/serp"
    assert api.bodies("/scraper/serp") == [{"query": "rag", "engine": "bing"}]  # None values dropped


def test_error_envelope_becomes_api_error() -> None:
    api = MockApi().add(
        "POST", "/scraper/extract", error(402, "Insufficient funds", {"code": "INSUFFICIENT_FUNDS"})
    )
    with pytest.raises(QuanticDataAPIError) as info:
        api.client().scrape({"url": "https://example.com/"})
    assert info.value.status == 402
    assert info.value.payload == {"code": "INSUFFICIENT_FUNDS"}
    assert "Insufficient funds" in str(info.value)


def test_non_json_error() -> None:
    api = MockApi().add("POST", "/scraper/extract", httpx.Response(500, text="upstream down"))
    with pytest.raises(QuanticDataAPIError, match="upstream down"):
        api.client().scrape({"url": "https://example.com/"})


def test_429_with_short_retry_after_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("langchain_quanticdata._client.time.sleep", slept.append)
    limited = error(429, "Rate limited")
    limited.headers["Retry-After"] = "1"
    api = MockApi().add("POST", "/scraper/map", limited, envelope({"links": [], "count": 0}))
    assert api.client().map({"url": "https://example.com/"})["count"] == 0
    assert slept == [1.0]


def test_429_with_long_retry_after_is_raised() -> None:
    limited = error(429, "Rate limited")
    limited.headers["Retry-After"] = "3600"
    api = MockApi().add("POST", "/scraper/map", limited)
    with pytest.raises(QuanticDataAPIError) as info:
        api.client().map({"url": "https://example.com/"})
    assert info.value.status == 429
    assert len(api.requests) == 1


def test_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUANTICDATA_API_KEY", raising=False)
    with pytest.raises(ValueError, match="QUANTICDATA_API_KEY"):
        QuanticDataClient()


def test_key_and_base_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUANTICDATA_API_KEY", "qd_env_key")
    monkeypatch.setenv("QUANTICDATA_API_BASE", "https://api.test.invalid/v1/")
    client = QuanticDataClient()
    assert client.api_key == "qd_env_key"
    assert client.base_url == "https://api.test.invalid/v1"


def test_default_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUANTICDATA_API_BASE", raising=False)
    assert resolve_base_url(None) == DEFAULT_BASE_URL == "https://api.quanticdata.io/v1"


def test_batch_poll_asks_for_content() -> None:
    api = MockApi().add("GET", "/scraper/batch/bt_example01", fixture("batch_done"))
    api.client().get_batch("bt_example01", since=4)
    params = api.requests[0].url.params
    assert params["include_content"] == "true"
    assert params["since"] == "4"


async def test_async_client() -> None:
    api = MockApi().add("POST", "/scraper/extract", fixture("extract_quotes"))
    payload = await api.async_client().scrape({"url": "https://quotes.toscrape.com/"})
    assert payload["title"] == "Quotes to Scrape"
