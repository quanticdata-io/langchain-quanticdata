from __future__ import annotations

import pytest

from langchain_quanticdata import QuanticDataJobError, QuanticDataLoader

from .helpers import MockApi, envelope, error, fixture, robots


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("langchain_quanticdata.document_loaders.time.sleep", lambda _s: None)


def loader(api: MockApi, url: str | list[str], **kwargs: object) -> QuanticDataLoader:
    kwargs.setdefault("robots", robots())
    return QuanticDataLoader(url, client=api.client(), async_client=api.async_client(), **kwargs)  # type: ignore[arg-type]


def test_scrape_mode() -> None:
    api = MockApi().add("POST", "/scraper/extract", fixture("extract_quotes"))
    docs = loader(api, "https://quotes.toscrape.com/").load()
    assert len(docs) == 1
    doc = docs[0]
    assert "Albert Einstein" in doc.page_content
    assert doc.metadata == {
        "source": "https://quotes.toscrape.com/",
        "title": "Quotes to Scrape",
        "status": 200,
        "final_url": "https://quotes.toscrape.com/",
        "engine": "tls",
        "language": "en",
        "mode": "scrape",
    }
    assert api.bodies("/scraper/extract") == [
        {"url": "https://quotes.toscrape.com/", "format": "markdown", "contentMode": "smart"}
    ]


def test_scrape_skips_robots_disallowed_and_failed_pages() -> None:
    page_404 = fixture("extract_quotes")["payload"] | {
        "url": "https://quotes.toscrape.com/missing",
        "status": 404,
    }
    api = MockApi().add("POST", "/scraper/extract", envelope(page_404))
    checker = robots({"blocked.example": "User-agent: *\nDisallow: /\n"})
    docs = loader(
        api, ["https://blocked.example/page", "https://quotes.toscrape.com/missing"], robots=checker
    ).load()
    assert docs == []
    assert [b["url"] for b in api.bodies("/scraper/extract")] == ["https://quotes.toscrape.com/missing"]


def test_scrape_raises_when_asked() -> None:
    api = MockApi().add("POST", "/scraper/extract", error(500, "Scraper unavailable"))
    with pytest.raises(Exception, match="Scraper unavailable"):
        loader(api, "https://example.com/", continue_on_failure=False).load()


def test_scrape_payment_errors_always_raise() -> None:
    api = MockApi().add("POST", "/scraper/extract", error(402, "Insufficient funds"))
    with pytest.raises(Exception, match="402"):
        loader(api, "https://example.com/").load()


def test_robots_can_be_turned_off() -> None:
    api = MockApi().add("POST", "/scraper/extract", fixture("extract_quotes"))
    checker = robots({"quotes.toscrape.com": "User-agent: *\nDisallow: /\n"})
    assert len(loader(api, "https://quotes.toscrape.com/", robots=checker, respect_robots=False).load()) == 1


def test_crawl_mode_polls_until_done() -> None:
    api = MockApi()
    api.add("POST", "/scraper/crawl", fixture("crawl_started"))
    api.add("GET", "/scraper/crawl/cr_example01", fixture("crawl_poll_1"), fixture("crawl_poll_2"))
    checker = robots({"quotes.toscrape.com": "User-agent: *\nDisallow: /admin/\n"})
    docs = loader(
        api,
        "https://quotes.toscrape.com/",
        mode="crawl",
        limit=3,
        depth=1,
        exclude=["/tag/"],
        robots=checker,
    ).load()
    assert [d.metadata["source"] for d in docs] == [
        "https://quotes.toscrape.com/",
        "https://quotes.toscrape.com/login",
    ]  # the 404 page is skipped
    assert docs[0].metadata["depth"] == 0
    assert docs[1].metadata["job_id"] == "cr_example01"
    assert api.bodies("/scraper/crawl") == [
        {
            "url": "https://quotes.toscrape.com/",
            "limit": 3,
            "depth": 1,
            "format": "markdown",
            "contentMode": "smart",
            "exclude": ["/tag/", "/admin/"],
        }
    ]
    polls = [r for r in api.requests if r.method == "GET"]
    assert "since" not in polls[0].url.params
    assert polls[1].url.params["since"] == "1"


def test_crawl_refuses_disallowed_seed() -> None:
    api = MockApi()
    checker = robots({"quotes.toscrape.com": "User-agent: *\nDisallow: /\n"})
    with pytest.raises(QuanticDataJobError, match=r"disallowed by robots.txt"):
        loader(api, "https://quotes.toscrape.com/", mode="crawl", robots=checker).load()
    assert api.requests == []


def test_crawl_failed_job() -> None:
    failed = fixture("crawl_poll_1")["payload"] | {
        "status": "failed",
        "error": "seed unreachable",
        "pages": [],
    }
    api = MockApi()
    api.add("POST", "/scraper/crawl", fixture("crawl_started"))
    api.add("GET", "/scraper/crawl/cr_example01", envelope(failed))
    with pytest.raises(QuanticDataJobError, match="seed unreachable"):
        loader(api, "https://quotes.toscrape.com/", mode="crawl").load()


def test_crawl_timeout() -> None:
    api = MockApi()
    api.add("POST", "/scraper/crawl", fixture("crawl_started"))
    running = fixture("crawl_poll_1")["payload"] | {"pages": []}
    api.add("GET", "/scraper/crawl/cr_example01", envelope(running))
    with pytest.raises(QuanticDataJobError, match="still running"):
        loader(api, "https://quotes.toscrape.com/", mode="crawl", timeout=-1).load()


def test_map_mode_filters_then_batches() -> None:
    api = MockApi()
    api.add("POST", "/scraper/map", fixture("map_books"))
    api.add("POST", "/scraper/batch", fixture("batch_started"))
    api.add("GET", "/scraper/batch/bt_example01", fixture("batch_done"))
    checker = robots(
        {"books.toscrape.com": "User-agent: *\nDisallow: /catalogue/category/books/mystery_3/\n"}
    )
    ld = loader(
        api,
        "https://books.toscrape.com/",
        mode="map",
        limit=10,
        exclude=["historical-fiction"],
        robots=checker,
        concurrency=3,
    )
    docs = ld.load()
    assert [d.metadata["title"] for d in docs] == [
        "All products | Books to Scrape - Sandbox",
        "Travel | Books to Scrape - Sandbox",
    ]
    assert api.bodies("/scraper/map") == [{"url": "https://books.toscrape.com/", "limit": 5000}]
    batch = api.bodies("/scraper/batch")[0]
    assert batch["urls"] == [
        "https://books.toscrape.com/index.html",
        "https://books.toscrape.com/catalogue/category/books_1/index.html",
        "https://books.toscrape.com/catalogue/category/books/travel_2/index.html",
    ]
    assert batch["concurrency"] == 3


def test_map_urls_include_glob() -> None:
    api = MockApi().add("POST", "/scraper/map", fixture("map_books"))
    urls = loader(api, "https://books.toscrape.com/", mode="map", include=["*/books/*_[0-9]/*"]).map_urls()
    assert urls == [
        "https://books.toscrape.com/catalogue/category/books/travel_2/index.html",
        "https://books.toscrape.com/catalogue/category/books/mystery_3/index.html",
        "https://books.toscrape.com/catalogue/category/books/historical-fiction_4/index.html",
    ]


def test_map_with_no_urls_makes_no_batch() -> None:
    api = MockApi().add(
        "POST", "/scraper/map", envelope({"url": "https://example.com/", "links": [], "count": 0})
    )
    assert loader(api, "https://example.com/", mode="map").load() == []
    assert not api.bodies("/scraper/batch")


def test_argument_validation() -> None:
    api = MockApi()
    with pytest.raises(ValueError, match="exactly one seed"):
        loader(api, ["https://a.example/", "https://b.example/"], mode="crawl")
    with pytest.raises(ValueError, match="At least one URL"):
        loader(api, [])
    with pytest.raises(ValueError, match="Unknown mode"):
        loader(api, "https://a.example/", mode="sitemap")


def test_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUANTICDATA_API_KEY", raising=False)
    with pytest.raises(ValueError, match="QUANTICDATA_API_KEY"):
        QuanticDataLoader("https://example.com/")


async def test_async_scrape_and_crawl(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr("langchain_quanticdata.document_loaders.asyncio.sleep", no_sleep)
    api = MockApi().add("POST", "/scraper/extract", fixture("extract_quotes"))
    docs = [d async for d in loader(api, ["https://quotes.toscrape.com/"] * 2).alazy_load()]
    assert len(docs) == 2

    api = MockApi()
    api.add("POST", "/scraper/crawl", fixture("crawl_started"))
    api.add("GET", "/scraper/crawl/cr_example01", fixture("crawl_poll_1"), fixture("crawl_poll_2"))
    docs = [d async for d in loader(api, "https://quotes.toscrape.com/", mode="crawl").alazy_load()]
    assert len(docs) == 2


async def test_async_map() -> None:
    api = MockApi()
    api.add("POST", "/scraper/map", fixture("map_books"))
    api.add("POST", "/scraper/batch", fixture("batch_started"))
    api.add("GET", "/scraper/batch/bt_example01", fixture("batch_done"))
    docs = await loader(api, "https://books.toscrape.com/", mode="map", limit=2).aload()
    assert len(docs) == 2
    assert len(api.bodies("/scraper/batch")[0]["urls"]) == 2
