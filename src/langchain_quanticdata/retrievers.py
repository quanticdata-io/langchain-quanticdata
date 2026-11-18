"""Retriever: search the live web, then read the top results as Documents."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from langchain_core.callbacks import AsyncCallbackManagerForRetrieverRun, CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import Field

from ._client import QuanticDataAPIError
from ._common import ClientConfig, is_click_url, organic_results
from ._robots import RobotsChecker

logger = logging.getLogger(__name__)


class QuanticDataSearchRetriever(BaseRetriever, ClientConfig):
    """Searches the web with the QuanticData SERP API and returns the top ``k`` results as
    Documents, with each page's Markdown when ``fetch_pages=True`` (the default) or the search
    snippet otherwise.

    A result is returned as its snippet when its page cannot be read: the engine gave a click
    address instead of the page URL, robots.txt disallows the page (``respect_robots``), or the
    fetch failed. ``metadata["fetched"]`` says which one you got.

    Example:
        .. code-block:: python

            from langchain_quanticdata import QuanticDataSearchRetriever

            retriever = QuanticDataSearchRetriever(k=3, country="us")
            docs = retriever.invoke("what is retrieval augmented generation")
    """

    k: int = Field(default=3, ge=1, le=20)
    """Number of results to return."""
    engine: Literal["google", "bing", "duckduckgo"] = "bing"
    """Search engine. Bing is the default because its organic results carry the page URLs, which
    the retriever then reads; Google results can carry click addresses that are not readable."""
    country: str | None = None
    """Country code to search from and to fetch pages from."""
    lang: str | None = None
    """Interface language of the search."""
    location: str | None = None
    """Human-readable search location."""
    fetch_pages: bool = True
    """Read each result page as Markdown. ``False`` returns the snippets only (one API call)."""
    content_mode: Literal["smart", "article", "full"] = "smart"
    """Content scope of each page."""
    max_tokens: int | None = Field(default=4000, ge=200)
    """Cap each page at about this many tokens. ``None`` = no cap."""
    focus_on_query: bool = False
    """Keep only the sections of each page that are relevant to the query."""
    respect_robots: bool = True
    """Read each site's robots.txt and do not fetch disallowed pages."""
    robots: RobotsChecker = Field(default_factory=RobotsChecker, exclude=True)
    """robots.txt checker (shared cache)."""

    def _search_body(self, query: str) -> dict[str, Any]:
        return {
            "query": query,
            "engine": self.engine,
            "num": max(10, self.k),
            "country": self.country,
            "lang": self.lang,
            "location": self.location,
        }

    def _scrape_body(self, url: str, query: str) -> dict[str, Any]:
        return {
            "url": url,
            "format": "markdown",
            "contentMode": self.content_mode,
            "max_tokens": self.max_tokens,
            "country": self.country,
            "query": query if self.focus_on_query else None,
        }

    @staticmethod
    def _snippet_doc(result: dict[str, Any], query: str, fetched: str) -> Document:
        return Document(
            page_content=str(result.get("snippet") or ""),
            metadata={
                "source": result["url"],
                "title": result.get("title"),
                "rank": result.get("rank"),
                "query": query,
                "fetched": fetched,
            },
        )

    @staticmethod
    def _page_doc(result: dict[str, Any], query: str, payload: dict[str, Any]) -> Document | None:
        status = payload.get("status")
        content = str(payload.get("content") or "")
        if payload.get("blockReason") or (isinstance(status, int) and status >= 400) or not content.strip():
            return None
        return Document(
            page_content=content,
            metadata={
                "source": result["url"],
                "final_url": payload.get("finalUrl"),
                "title": payload.get("title") or result.get("title"),
                "rank": result.get("rank"),
                "snippet": result.get("snippet"),
                "query": query,
                "fetched": "page",
            },
        )

    def _readable(self, url: str) -> str | None:
        """Why a result page will not be fetched, or ``None``."""
        if is_click_url(url):
            return "snippet:click-url"
        if self.respect_robots and not self.robots.allowed(url):
            return "snippet:robots"
        return None

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        client = self._sync_client()
        results = organic_results(client.search(self._search_body(query)), self.k)
        if not self.fetch_pages:
            return [self._snippet_doc(r, query, "snippet") for r in results]
        docs: list[Document] = []
        for result in results:
            reason = self._readable(result["url"])
            if reason is None:
                try:
                    doc = self._page_doc(
                        result, query, client.scrape(self._scrape_body(result["url"], query))
                    )
                except QuanticDataAPIError as exc:
                    if exc.status in (401, 402):
                        raise
                    logger.warning("Could not read %s: %s", result["url"], exc)
                    doc = None
                if doc is not None:
                    docs.append(doc)
                    continue
                reason = "snippet:fetch-failed"
            docs.append(self._snippet_doc(result, query, reason))
        return docs

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        client = self._async_client()
        results = organic_results(await client.search(self._search_body(query)), self.k)
        if not self.fetch_pages:
            return [self._snippet_doc(r, query, "snippet") for r in results]

        async def one(result: dict[str, Any]) -> Document:
            url = result["url"]
            if is_click_url(url):
                return self._snippet_doc(result, query, "snippet:click-url")
            if self.respect_robots and not await self.robots.aallowed(url):
                return self._snippet_doc(result, query, "snippet:robots")
            try:
                doc = self._page_doc(result, query, await client.scrape(self._scrape_body(url, query)))
            except QuanticDataAPIError as exc:
                if exc.status in (401, 402):
                    raise
                logger.warning("Could not read %s: %s", url, exc)
                doc = None
            return doc or self._snippet_doc(result, query, "snippet:fetch-failed")

        return list(await asyncio.gather(*(one(r) for r in results)))
