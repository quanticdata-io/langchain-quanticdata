"""Document loader: pages, whole sites (crawl) or a site's URL list (map + batch) as Documents."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import Any, Literal

from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document

from ._client import (
    AsyncQuanticDataClient,
    QuanticDataAPIError,
    QuanticDataClient,
    QuanticDataJobError,
    resolve_api_key,
    resolve_base_url,
)
from ._robots import RobotsChecker

logger = logging.getLogger(__name__)

Mode = Literal["scrape", "crawl", "map"]

#: Documented cap of one ``/scraper/batch`` job.
BATCH_MAX_URLS = 5000


def _matches(url: str, patterns: Sequence[str]) -> bool:
    return any((fnmatch.fnmatchcase(url, p) if "*" in p else p in url) for p in patterns)


def _failure(item: Mapping[str, Any]) -> str | None:
    """Why a page cannot become a Document, or ``None`` when it can."""
    if item.get("error"):
        return str(item["error"])
    if item.get("blockReason"):
        return f"blocked ({item['blockReason']})"
    status = item.get("status")
    if isinstance(status, int) and status >= 400:
        return f"HTTP {status}"
    return None


class QuanticDataLoader(BaseLoader):
    """Loads web pages as LangChain Documents through the QuanticData API.

    Three modes:

    - ``scrape``: each URL in ``url`` through ``POST /scraper/extract``, one Document per URL.
    - ``crawl``: a breadth-first crawl from the seed ``url`` (``POST /scraper/crawl``, then
      ``GET /scraper/crawl/{id}`` until the job finishes), one Document per crawled page.
    - ``map``: the site's URLs from its sitemaps and homepage links (``POST /scraper/map``),
      filtered by ``include``/``exclude``/``search``, then fetched with one ``POST /scraper/batch``
      job, one Document per page.

    Pages that fail (HTTP status 400 or more, an error or a block) are skipped with a warning
    unless ``continue_on_failure=False``.

    Setup:
        .. code-block:: bash

            pip install git+https://github.com/quanticdata-io/langchain-quanticdata
            export QUANTICDATA_API_KEY="your-key"

    Instantiate and load:
        .. code-block:: python

            from langchain_quanticdata import QuanticDataLoader

            loader = QuanticDataLoader("https://quotes.toscrape.com/", mode="crawl", limit=10, depth=1)
            for doc in loader.lazy_load():
                print(doc.metadata["source"], len(doc.page_content))
    """

    def __init__(
        self,
        url: str | Sequence[str],
        *,
        mode: Mode = "scrape",
        api_key: str | None = None,
        base_url: str | None = None,
        format: Literal["markdown", "text", "html"] = "markdown",
        content_mode: Literal["smart", "article", "full"] = "smart",
        render: bool = False,
        country: str | None = None,
        limit: int = 50,
        depth: int = 3,
        include: Sequence[str] | None = None,
        exclude: Sequence[str] | None = None,
        search: str | None = None,
        include_subdomains: bool = False,
        concurrency: int = 5,
        respect_robots: bool = True,
        robots_user_agent: str = "*",
        continue_on_failure: bool = True,
        poll_interval: float = 2.0,
        timeout: float = 900.0,
        params: Mapping[str, Any] | None = None,
        client: QuanticDataClient | None = None,
        async_client: AsyncQuanticDataClient | None = None,
        robots: RobotsChecker | None = None,
    ) -> None:
        """Create the loader.

        Args:
            url: One URL, or several for ``mode="scrape"``. ``crawl`` and ``map`` take one seed URL.
            mode: ``scrape``, ``crawl`` or ``map`` (see the class docstring).
            api_key: API key; defaults to ``QUANTICDATA_API_KEY``.
            base_url: API base URL; defaults to ``QUANTICDATA_API_BASE`` or the public API.
            format: ``markdown``, ``text`` or ``html``.
            content_mode: ``smart``, ``article`` or ``full``.
            render: Render every page in a headless browser (billed at the render rate).
            country: Country code of the exit used to fetch the pages.
            limit: ``crawl``: maximum pages (API cap 500, billed up front on this number, unfetched
                pages refunded). ``map``: maximum URLs to fetch (API cap 5000).
            depth: ``crawl``: maximum link depth from the seed (API cap 10).
            include: URL substrings or globs to keep (``crawl`` and ``map``).
            exclude: URL substrings or globs to drop (``crawl`` and ``map``).
            search: ``map``: only URLs containing this substring.
            include_subdomains: ``crawl`` and ``map``: also follow subdomains of the seed host.
            concurrency: ``map``: simultaneous fetches of the batch job (1 to 20);
                ``scrape`` with ``alazy_load``: simultaneous requests.
            respect_robots: Read each site's robots.txt on your side and skip disallowed URLs.
            robots_user_agent: User agent whose robots.txt group applies (``*`` by default).
            continue_on_failure: Skip failed pages with a warning instead of raising.
            poll_interval: Seconds between polls of a crawl or batch job.
            timeout: Seconds before a crawl or batch job is given up.
            params: Extra documented API parameters merged into the request body as is.
            client: Pre-built synchronous client.
            async_client: Pre-built asynchronous client.
            robots: Pre-built robots.txt checker.
        """
        urls = [url] if isinstance(url, str) else list(url)
        if not urls:
            raise ValueError("At least one URL is required.")
        if mode in ("crawl", "map") and len(urls) != 1:
            raise ValueError(f"mode={mode!r} takes exactly one seed URL.")
        if mode not in ("scrape", "crawl", "map"):
            raise ValueError(f"Unknown mode {mode!r}: use 'scrape', 'crawl' or 'map'.")
        self.urls = urls
        self.mode: Mode = mode
        self.format = format
        self.content_mode = content_mode
        self.render = render
        self.country = country
        self.limit = limit
        self.depth = depth
        self.include = list(include or [])
        self.exclude = list(exclude or [])
        self.search = search
        self.include_subdomains = include_subdomains
        self.concurrency = concurrency
        self.respect_robots = respect_robots
        self.continue_on_failure = continue_on_failure
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.params = dict(params or {})
        if client is None and async_client is None:
            resolve_api_key(api_key)  # fail early, with a clear message, when no key is set
        self._api_key = api_key
        self._base_url = resolve_base_url(base_url)
        self._client = client
        self._async_client = async_client
        self.robots = robots or RobotsChecker(robots_user_agent)

    # -- clients ---------------------------------------------------------------------------

    def _sync(self) -> QuanticDataClient:
        if self._client is None:
            self._client = QuanticDataClient(self._api_key, base_url=self._base_url)
        return self._client

    def _async(self) -> AsyncQuanticDataClient:
        if self._async_client is None:
            self._async_client = AsyncQuanticDataClient(self._api_key, base_url=self._base_url)
        return self._async_client

    # -- request bodies ----------------------------------------------------------------------

    def _scrape_body(self, url: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "url": url,
            "format": self.format,
            "contentMode": self.content_mode,
            "render": self.render or None,
            "country": self.country,
        }
        body.update(self.params)
        return body

    def _crawl_body(self, extra_exclude: Sequence[str]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "url": self.urls[0],
            "limit": self.limit,
            "depth": self.depth,
            "format": self.format,
            "contentMode": self.content_mode,
            "render": self.render or None,
            "allowSubdomains": self.include_subdomains or None,
            "include": self.include or None,
            "exclude": [*self.exclude, *extra_exclude] or None,
            "country": self.country,
        }
        body.update(self.params)
        return body

    def _map_body(self) -> dict[str, Any]:
        return {
            "url": self.urls[0],
            # Local filters can drop URLs, so ask the map for as many as it returns when they are set.
            "limit": BATCH_MAX_URLS if (self.include or self.exclude) else min(self.limit, BATCH_MAX_URLS),
            "search": self.search,
            "includeSubdomains": self.include_subdomains or None,
            "country": self.country,
        }

    def _batch_body(self, urls: Sequence[str]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "urls": list(urls),
            "format": self.format,
            "contentMode": self.content_mode,
            "render": self.render or None,
            "concurrency": self.concurrency,
            "country": self.country,
        }
        body.update(self.params)
        return body

    # -- shaping -----------------------------------------------------------------------------

    def _document(self, item: Mapping[str, Any], **extra: Any) -> Document | None:
        url = str(item.get("url") or "")
        reason = _failure(item)
        if reason is not None:
            if not self.continue_on_failure:
                raise QuanticDataJobError(f"{url}: {reason}")
            logger.warning("Skipping %s: %s", url, reason)
            return None
        metadata: dict[str, Any] = {"source": url, "title": item.get("title"), "status": item.get("status")}
        if item.get("finalUrl"):
            metadata["final_url"] = item["finalUrl"]
        if item.get("engine"):
            metadata["engine"] = item["engine"]
        if item.get("depth") is not None:
            metadata["depth"] = item["depth"]
        if isinstance(item.get("metadata"), Mapping):
            for key in ("description", "language", "canonical", "publishedTime", "author"):
                value = item["metadata"].get(key)
                if value:
                    metadata[key] = value
        metadata.update(extra)
        metadata["mode"] = self.mode
        return Document(page_content=str(item.get("content") or ""), metadata=metadata)

    def _skip_url(self, url: str) -> None:
        if not self.continue_on_failure:
            raise QuanticDataJobError(f"{url}: disallowed by robots.txt")
        logger.warning("Skipping %s: disallowed by robots.txt", url)

    def _filter(self, urls: Sequence[str]) -> list[str]:
        kept = [u for u in urls if (not self.include or _matches(u, self.include))]
        return [u for u in kept if not (self.exclude and _matches(u, self.exclude))]

    @staticmethod
    def _finished(view: Mapping[str, Any]) -> bool:
        return view.get("status") != "running" and not view.get("hasMore")

    def _check_status(self, kind: str, view: Mapping[str, Any]) -> None:
        if view.get("status") in ("failed", "cancelled"):
            raise QuanticDataJobError(
                f"{kind} job {view.get('id')} {view.get('status')}: {view.get('error') or 'no detail'}"
            )

    # -- sync --------------------------------------------------------------------------------

    def lazy_load(self) -> Iterator[Document]:
        if self.mode == "scrape":
            yield from self._lazy_scrape()
        elif self.mode == "crawl":
            yield from self._lazy_crawl()
        else:
            yield from self._lazy_map()

    def map_urls(self) -> list[str]:
        """The URLs ``mode="map"`` would fetch: map result, filters and robots.txt applied."""
        payload = self._sync().map(self._map_body())
        urls = self._filter([str(u) for u in payload.get("links") or []])
        if self.respect_robots:
            urls = [u for u in urls if self.robots.allowed(u)]
        return urls[: self.limit]

    def _lazy_scrape(self) -> Iterator[Document]:
        for url in self.urls:
            if self.respect_robots and not self.robots.allowed(url):
                self._skip_url(url)
                continue
            try:
                payload = self._sync().scrape(self._scrape_body(url))
            except QuanticDataAPIError as exc:
                if exc.status in (401, 402, 403) or not self.continue_on_failure:
                    raise
                logger.warning("Skipping %s: %s", url, exc)
                continue
            doc = self._document(payload)
            if doc is not None:
                yield doc

    def _robots_exclude(self) -> list[str]:
        seed = self.urls[0]
        rules = self.robots.rules_for(seed)
        if not rules.allowed(seed):
            raise QuanticDataJobError(f"{seed}: the seed URL is disallowed by robots.txt")
        return rules.disallowed_paths()

    def _lazy_crawl(self) -> Iterator[Document]:
        extra = self._robots_exclude() if self.respect_robots else []
        client = self._sync()
        job = client.start_crawl(self._crawl_body(extra))
        job_id = str(job["id"])
        deadline = time.monotonic() + self.timeout
        cursor: int | None = None
        while True:
            view = client.get_crawl(job_id, since=cursor)
            for page in view.get("pages") or []:
                url = str(page.get("url") or "")
                if self.respect_robots and not self.robots.allowed(url):
                    logger.warning("Dropping %s: disallowed by robots.txt", url)
                    continue
                doc = self._document(page, job_id=job_id)
                if doc is not None:
                    yield doc
            cursor = view.get("nextCursor", cursor)
            self._check_status("Crawl", view)
            if self._finished(view):
                return
            if time.monotonic() > deadline:
                raise QuanticDataJobError(f"Crawl job {job_id} still running after {self.timeout}s")
            if not view.get("hasMore"):
                time.sleep(self.poll_interval)

    def _lazy_map(self) -> Iterator[Document]:
        urls = self.map_urls()
        if not urls:
            return
        client = self._sync()
        job = client.start_batch(self._batch_body(urls))
        job_id = str(job["id"])
        deadline = time.monotonic() + self.timeout
        cursor: int | None = None
        while True:
            view = client.get_batch(job_id, since=cursor)
            for item in view.get("items") or []:
                doc = self._document(item, job_id=job_id)
                if doc is not None:
                    yield doc
            cursor = view.get("nextCursor", cursor)
            self._check_status("Batch", view)
            if self._finished(view):
                return
            if time.monotonic() > deadline:
                raise QuanticDataJobError(f"Batch job {job_id} still running after {self.timeout}s")
            if not view.get("hasMore"):
                time.sleep(self.poll_interval)

    # -- async -------------------------------------------------------------------------------

    async def alazy_load(self) -> AsyncIterator[Document]:
        if self.mode == "scrape":
            async for doc in self._alazy_scrape():
                yield doc
        elif self.mode == "crawl":
            async for doc in self._alazy_crawl():
                yield doc
        else:
            async for doc in self._alazy_map():
                yield doc

    async def amap_urls(self) -> list[str]:
        """Async twin of :meth:`map_urls`."""
        payload = await self._async().map(self._map_body())
        urls = self._filter([str(u) for u in payload.get("links") or []])
        if self.respect_robots:
            urls = [u for u in urls if await self.robots.aallowed(u)]
        return urls[: self.limit]

    async def _alazy_scrape(self) -> AsyncIterator[Document]:
        semaphore = asyncio.Semaphore(max(1, self.concurrency))

        async def one(url: str) -> Document | None:
            async with semaphore:
                if self.respect_robots and not await self.robots.aallowed(url):
                    self._skip_url(url)
                    return None
                try:
                    payload = await self._async().scrape(self._scrape_body(url))
                except QuanticDataAPIError as exc:
                    if exc.status in (401, 402, 403) or not self.continue_on_failure:
                        raise
                    logger.warning("Skipping %s: %s", url, exc)
                    return None
                return self._document(payload)

        for doc in await asyncio.gather(*(one(u) for u in self.urls)):
            if doc is not None:
                yield doc

    async def _alazy_crawl(self) -> AsyncIterator[Document]:
        extra: list[str] = []
        if self.respect_robots:
            rules = await self.robots.arules_for(self.urls[0])
            if not rules.allowed(self.urls[0]):
                raise QuanticDataJobError(f"{self.urls[0]}: the seed URL is disallowed by robots.txt")
            extra = rules.disallowed_paths()
        client = self._async()
        job = await client.start_crawl(self._crawl_body(extra))
        job_id = str(job["id"])
        deadline = time.monotonic() + self.timeout
        cursor: int | None = None
        while True:
            view = await client.get_crawl(job_id, since=cursor)
            for page in view.get("pages") or []:
                url = str(page.get("url") or "")
                if self.respect_robots and not await self.robots.aallowed(url):
                    logger.warning("Dropping %s: disallowed by robots.txt", url)
                    continue
                doc = self._document(page, job_id=job_id)
                if doc is not None:
                    yield doc
            cursor = view.get("nextCursor", cursor)
            self._check_status("Crawl", view)
            if self._finished(view):
                return
            if time.monotonic() > deadline:
                raise QuanticDataJobError(f"Crawl job {job_id} still running after {self.timeout}s")
            if not view.get("hasMore"):
                await asyncio.sleep(self.poll_interval)

    async def _alazy_map(self) -> AsyncIterator[Document]:
        urls = await self.amap_urls()
        if not urls:
            return
        client = self._async()
        job = await client.start_batch(self._batch_body(urls))
        job_id = str(job["id"])
        deadline = time.monotonic() + self.timeout
        cursor: int | None = None
        while True:
            view = await client.get_batch(job_id, since=cursor)
            for item in view.get("items") or []:
                doc = self._document(item, job_id=job_id)
                if doc is not None:
                    yield doc
            cursor = view.get("nextCursor", cursor)
            self._check_status("Batch", view)
            if self._finished(view):
                return
            if time.monotonic() > deadline:
                raise QuanticDataJobError(f"Batch job {job_id} still running after {self.timeout}s")
            if not view.get("hasMore"):
                await asyncio.sleep(self.poll_interval)
