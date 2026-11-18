from __future__ import annotations

import pytest

from langchain_quanticdata import QuanticDataSearchRetriever

from .helpers import MockApi, error, fixture, robots


def test_snippets_only() -> None:
    api = MockApi().add("POST", "/scraper/serp", fixture("serp_bing"))
    retriever = QuanticDataSearchRetriever(client=api.client(), k=2, fetch_pages=False, robots=robots())
    docs = retriever.invoke("what is retrieval augmented generation")
    assert [d.metadata["source"] for d in docs] == [
        "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
        "https://www.databricks.com/blog/what-is-retrieval-augmented-generation",
    ]
    assert docs[0].metadata["fetched"] == "snippet"
    assert docs[0].page_content.startswith("Retrieval-augmented generation (RAG)")
    assert api.bodies("/scraper/serp") == [
        {"query": "what is retrieval augmented generation", "engine": "bing", "num": 10}
    ]


def test_fetch_pages_with_fallbacks() -> None:
    api = MockApi().add("POST", "/scraper/serp", fixture("serp_bing"))
    api.add("POST", "/scraper/extract", fixture("extract_quotes"), error(500, "timeout"))
    checker = robots({"www.databricks.com": "User-agent: *\nDisallow: /blog/\n"})
    retriever = QuanticDataSearchRetriever(client=api.client(), k=3, robots=checker, focus_on_query=True)
    docs = retriever.invoke("rag")
    assert [d.metadata["fetched"] for d in docs] == ["page", "snippet:robots", "snippet:fetch-failed"]
    assert "Albert Einstein" in docs[0].page_content  # the recorded page stands in for the first result
    assert docs[0].metadata["rank"] == 1
    scraped = api.bodies("/scraper/extract")
    assert [b["url"] for b in scraped] == [
        "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
        "https://aws.amazon.com/what-is/retrieval-augmented-generation/",
    ]
    assert scraped[0]["query"] == "rag"
    assert scraped[0]["max_tokens"] == 4000


def test_click_urls_are_not_fetched() -> None:
    api = MockApi().add("POST", "/scraper/serp", fixture("serp_google"))
    api.add("POST", "/scraper/extract", fixture("extract_quotes"))
    retriever = QuanticDataSearchRetriever(client=api.client(), engine="google", k=3, robots=robots())
    docs = retriever.invoke("rag")
    assert [d.metadata["fetched"] for d in docs] == ["page", "snippet:click-url", "snippet:click-url"]
    assert len(api.bodies("/scraper/extract")) == 1


def test_payment_error_raises() -> None:
    api = MockApi().add("POST", "/scraper/serp", fixture("serp_bing"))
    api.add("POST", "/scraper/extract", error(402, "Insufficient funds"))
    retriever = QuanticDataSearchRetriever(client=api.client(), k=1, robots=robots())
    with pytest.raises(Exception, match="402"):
        retriever.invoke("rag")


async def test_async_retriever() -> None:
    api = MockApi().add("POST", "/scraper/serp", fixture("serp_bing"))
    api.add("POST", "/scraper/extract", fixture("extract_quotes"))
    retriever = QuanticDataSearchRetriever(async_client=api.async_client(), k=2, robots=robots())
    docs = await retriever.ainvoke("rag")
    assert [d.metadata["fetched"] for d in docs] == ["page", "page"]

    api = MockApi().add("POST", "/scraper/serp", fixture("serp_google"))
    retriever = QuanticDataSearchRetriever(async_client=api.async_client(), k=2, fetch_pages=False)
    assert len(await retriever.ainvoke("rag")) == 2
