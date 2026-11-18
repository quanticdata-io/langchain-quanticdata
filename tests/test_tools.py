from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_tests.unit_tests import ToolsUnitTests
from pydantic import SecretStr

from langchain_quanticdata import QuanticDataScrape, QuanticDataSearch

from .helpers import MockApi, envelope, error, fixture


class TestSearchStandard(ToolsUnitTests):
    @property
    def tool_constructor(self) -> type[BaseTool]:
        return QuanticDataSearch

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {"api_key": "qd_test_key"}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"query": "what is retrieval augmented generation"}

    @property
    def init_from_env_params(self) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
        return ({"QUANTICDATA_API_KEY": "qd_env_key"}, {}, {"api_key": "qd_env_key"})


class TestScrapeStandard(ToolsUnitTests):
    @property
    def tool_constructor(self) -> type[BaseTool]:
        return QuanticDataScrape

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {"api_key": "qd_test_key"}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"url": "https://quotes.toscrape.com/", "query": "Einstein"}

    @property
    def init_from_env_params(self) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
        return ({"QUANTICDATA_API_KEY": "qd_env_key"}, {}, {"api_key": "qd_env_key"})


def test_search_shapes_results() -> None:
    api = MockApi().add("POST", "/scraper/serp", fixture("serp_google"))
    tool = QuanticDataSearch(client=api.client(), country="us", lang="en", max_results=2)
    out = tool.invoke({"query": "what is retrieval augmented generation"})
    assert [r["rank"] for r in out["results"]] == [1, 2]
    first = out["results"][0]
    assert first["url"].startswith("https://builder.aws.com/")
    assert first["source"] == "builder.aws.com"
    assert first["snippet"].startswith("It is a technique")
    assert "ai_overview" not in out  # the recorded page had none
    assert api.bodies("/scraper/serp") == [
        {
            "query": "what is retrieval augmented generation",
            "engine": "google",
            "num": 10,
            "country": "us",
            "lang": "en",
        }
    ]


def test_search_returns_ai_overview_when_present() -> None:
    payload = fixture("serp_google")["payload"]
    payload["ai_overview"] = "Synthetic overview text for the test."
    payload["ai_overview_references"] = [{"title": "Example", "link": "https://example.com/"}]
    api = MockApi().add("POST", "/scraper/serp", envelope(payload))
    out = QuanticDataSearch(client=api.client()).invoke({"query": "q"})
    assert out["ai_overview"] == "Synthetic overview text for the test."
    assert out["ai_overview_references"][0]["link"] == "https://example.com/"

    api = MockApi().add("POST", "/scraper/serp", envelope(payload))
    out = QuanticDataSearch(client=api.client(), include_ai_overview=False).invoke({"query": "q"})
    assert "ai_overview" not in out


def test_search_extra_params_and_engine() -> None:
    api = MockApi().add("POST", "/scraper/serp", fixture("serp_bing"))
    QuanticDataSearch(client=api.client(), engine="bing", num=5, extra_params={"safe": "active"}).invoke(
        {"query": "q"}
    )
    assert api.bodies("/scraper/serp")[0] == {"query": "q", "engine": "bing", "num": 5, "safe": "active"}


def test_search_error_is_returned_to_the_agent() -> None:
    api = MockApi().add("POST", "/scraper/serp", error(429, "Engine blocked every attempt"))
    tool = QuanticDataSearch(client=api.client())
    message = tool.invoke({"type": "tool_call", "id": "1", "name": tool.name, "args": {"query": "q"}})
    assert isinstance(message, ToolMessage)
    assert "HTTP 429" in str(message.content)


def test_scrape_content_and_artifact() -> None:
    api = MockApi().add("POST", "/scraper/extract", fixture("extract_quotes"))
    tool = QuanticDataScrape(client=api.client(), max_tokens=1000)
    message = tool.invoke(
        {
            "type": "tool_call",
            "id": "call-1",
            "name": tool.name,
            "args": {"url": "https://quotes.toscrape.com/", "query": "Einstein"},
        }
    )
    assert isinstance(message, ToolMessage)
    assert "Albert Einstein" in str(message.content)
    assert message.artifact["title"] == "Quotes to Scrape"
    assert message.artifact["engine"] == "tls"
    assert api.bodies("/scraper/extract") == [
        {
            "url": "https://quotes.toscrape.com/",
            "format": "markdown",
            "contentMode": "smart",
            "engine": "auto",
            "max_tokens": 1000,
            "query": "Einstein",
        }
    ]


def test_scrape_direct_invoke_returns_text() -> None:
    api = MockApi().add("POST", "/scraper/extract", fixture("extract_quotes"))
    text = QuanticDataScrape(client=api.client()).invoke({"url": "https://quotes.toscrape.com/"})
    assert text.startswith("# [Quotes to Scrape]")


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"status": 404}, "HTTP 404"),
        ({"blockReason": "challenge"}, "could not be retrieved"),
        ({"content": "", "jsLikely": True}, "render=True"),
    ],
)
def test_scrape_failures(change: dict[str, Any], expected: str) -> None:
    payload = fixture("extract_quotes")["payload"] | change
    api = MockApi().add("POST", "/scraper/extract", envelope(payload))
    tool = QuanticDataScrape(client=api.client())
    message = tool.invoke(
        {"type": "tool_call", "id": "1", "name": tool.name, "args": {"url": "https://example.com/"}}
    )
    assert expected in str(message.content)


def test_render_option() -> None:
    api = MockApi().add("POST", "/scraper/extract", fixture("extract_quotes"))
    QuanticDataScrape(client=api.client(), render=True, max_tokens=None, country="de").invoke(
        {"url": "https://quotes.toscrape.com/"}
    )
    body = api.bodies("/scraper/extract")[0]
    assert body["render"] is True
    assert body["country"] == "de"
    assert "max_tokens" not in body


def test_tool_schema_for_models() -> None:
    tool = QuanticDataScrape(api_key=SecretStr("qd_test_key"))
    schema = convert_to_openai_tool(tool)["function"]["parameters"]
    assert set(schema["properties"]) == {"url", "query"}
    assert schema["required"] == ["url"]
    json.dumps(schema)


def test_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUANTICDATA_API_KEY", raising=False)
    with pytest.raises(ValueError, match="QUANTICDATA_API_KEY"):
        QuanticDataSearch()


async def test_async_search_and_scrape() -> None:
    api = MockApi().add("POST", "/scraper/serp", fixture("serp_bing"))
    api.add("POST", "/scraper/extract", fixture("extract_quotes"))
    out = await QuanticDataSearch(async_client=api.async_client()).ainvoke({"query": "q"})
    assert out["results"][0]["source"] == "en.wikipedia.org"
    text = await QuanticDataScrape(async_client=api.async_client()).ainvoke(
        {"url": "https://quotes.toscrape.com/"}
    )
    assert "Einstein" in text
