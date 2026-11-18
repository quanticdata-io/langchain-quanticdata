"""LangChain tools: web search (``/scraper/serp``) and page to Markdown (``/scraper/extract``)."""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.callbacks import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool, ToolException
from pydantic import BaseModel, Field

from ._client import QuanticDataAPIError
from ._common import ClientConfig, organic_results


class QuanticDataSearchInput(BaseModel):
    """Input of :class:`QuanticDataSearch`."""

    query: str = Field(description="The search query, as you would type it into a search engine.")


class QuanticDataSearch(BaseTool, ClientConfig):
    """Web search through the QuanticData SERP API.

    Setup:
        Install from source and set ``QUANTICDATA_API_KEY``.

        .. code-block:: bash

            pip install git+https://github.com/quanticdata-io/langchain-quanticdata
            export QUANTICDATA_API_KEY="your-key"

    Instantiate:
        .. code-block:: python

            from langchain_quanticdata import QuanticDataSearch

            tool = QuanticDataSearch(max_results=5, country="us", lang="en")

    Invoke:
        .. code-block:: python

            tool.invoke({"query": "what is retrieval augmented generation"})

    Returns a dict with ``query``, ``results`` (``rank``, ``title``, ``url``, ``snippet`` and,
    when present, ``source`` and ``date``) and, for Google, ``ai_overview`` and
    ``ai_overview_references`` when the page had an AI Overview.
    """

    name: str = "quanticdata_search"
    description: str = (
        "Search the web and get ranked results (title, url, snippet). On Google it also returns "
        "the AI Overview text when the results page has one. Use it for current events and facts "
        "you need to look up. Input: a search query."
    )
    args_schema: type[BaseModel] = QuanticDataSearchInput
    handle_tool_error: bool = True

    engine: Literal["google", "bing", "duckduckgo"] = "google"
    """Search engine."""
    num: int = Field(default=10, ge=1, le=100)
    """Results to request from the engine."""
    max_results: int | None = Field(default=None, ge=1)
    """Keep at most this many organic results in the tool output."""
    country: str | None = None
    """Country code (``us``, ``de``...) to search from."""
    lang: str | None = None
    """Interface language (``en``, ``it``...)."""
    location: str | None = None
    """Human-readable search location, for example ``"Milan, Italy"``."""
    device: Literal["desktop", "mobile", "ios", "android"] | None = None
    """Device to search as."""
    include_ai_overview: bool = True
    """Return Google's AI Overview text and references when present."""
    extra_params: dict[str, Any] = Field(default_factory=dict)
    """Any other documented ``/scraper/serp`` parameter, sent as is (for example ``{"safe": "active"}``)."""

    def _body(self, query: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": query,
            "engine": self.engine,
            "num": self.num,
            "country": self.country,
            "lang": self.lang,
            "location": self.location,
            "device": self.device,
        }
        body.update(self.extra_params)
        return body

    def _shape(self, query: str, payload: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {"query": query, "results": organic_results(payload, self.max_results)}
        if self.include_ai_overview and payload.get("ai_overview"):
            out["ai_overview"] = payload["ai_overview"]
            out["ai_overview_references"] = payload.get("ai_overview_references") or []
        return out

    def _run(self, query: str, run_manager: CallbackManagerForToolRun | None = None) -> dict[str, Any]:
        try:
            payload = self._sync_client().search(self._body(query))
        except QuanticDataAPIError as exc:
            raise ToolException(f"Search failed: {exc}") from exc
        return self._shape(query, payload)

    async def _arun(
        self, query: str, run_manager: AsyncCallbackManagerForToolRun | None = None
    ) -> dict[str, Any]:
        try:
            payload = await self._async_client().search(self._body(query))
        except QuanticDataAPIError as exc:
            raise ToolException(f"Search failed: {exc}") from exc
        return self._shape(query, payload)


class QuanticDataScrapeInput(BaseModel):
    """Input of :class:`QuanticDataScrape`."""

    url: str = Field(description="The http or https URL of the page to read.")
    query: str | None = Field(
        default=None,
        description="Optional: what you are looking for on the page. Only relevant sections are returned.",
    )


class QuanticDataScrape(BaseTool, ClientConfig):
    """Reads one web page as Markdown through the QuanticData scraping API.

    Instantiate:
        .. code-block:: python

            from langchain_quanticdata import QuanticDataScrape

            tool = QuanticDataScrape(max_tokens=4000)

    Invoke:
        .. code-block:: python

            tool.invoke({"url": "https://quotes.toscrape.com/"})

    The tool's content is the page text; its artifact (``response_format="content_and_artifact"``)
    holds the page metadata: ``url``, ``final_url``, ``status``, ``title``, ``engine``,
    ``metadata``.
    """

    name: str = "quanticdata_scrape"
    description: str = (
        "Read a web page and get its main content as Markdown. Input: the page URL and, optionally, "
        "what you are looking for on it."
    )
    args_schema: type[BaseModel] = QuanticDataScrapeInput
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"
    handle_tool_error: bool = True

    format: Literal["markdown", "text", "html"] = "markdown"
    """Output format."""
    content_mode: Literal["smart", "article", "full"] = "smart"
    """``smart``: page without navigation, footer and cookie banners; ``article``: main article;
    ``full``: the entire body."""
    engine: Literal["auto", "tls", "fetch", "render"] = "auto"
    """Fetch engine; ``render`` always uses a headless browser."""
    render: bool = False
    """Force a headless browser render (for pages that need JavaScript). Billed at the render rate."""
    max_tokens: int | None = Field(default=8000, ge=200)
    """Cap the Markdown at about this many tokens, cut at a section boundary. ``None`` = no cap."""
    links_mode: Literal["inline", "footnote", "strip"] | None = None
    """How links are rendered; ``strip`` keeps only the link text."""
    images_mode: Literal["inline", "alt", "strip"] | None = None
    """How images are rendered."""
    country: str | None = None
    """Country code of the exit used to fetch the page."""
    extra_params: dict[str, Any] = Field(default_factory=dict)
    """Any other documented ``/scraper/extract`` parameter, sent as is (for example
    ``{"waitForSelector": "#main"}``)."""

    def _body(self, url: str, query: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "url": url,
            "format": self.format,
            "contentMode": self.content_mode,
            "engine": self.engine,
            "render": self.render or None,
            "max_tokens": self.max_tokens,
            "links_mode": self.links_mode,
            "images_mode": self.images_mode,
            "country": self.country,
            "query": query,
        }
        body.update(self.extra_params)
        return body

    @staticmethod
    def _shape(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        status = payload.get("status")
        if payload.get("blockReason"):
            raise ToolException(f"The page could not be retrieved ({payload['blockReason']}).")
        if isinstance(status, int) and status >= 400:
            raise ToolException(f"The page answered HTTP {status}.")
        content = str(payload.get("content") or "")
        if not content.strip() and payload.get("jsLikely"):
            raise ToolException("The page needs JavaScript: create the tool with render=True.")
        artifact = {
            "url": payload.get("url"),
            "final_url": payload.get("finalUrl"),
            "status": status,
            "title": payload.get("title"),
            "engine": payload.get("engine"),
            "metadata": payload.get("metadata") or {},
        }
        return content, artifact

    def _run(
        self,
        url: str,
        query: str | None = None,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> tuple[str, dict[str, Any]]:
        try:
            payload = self._sync_client().scrape(self._body(url, query))
        except QuanticDataAPIError as exc:
            raise ToolException(f"Scrape failed: {exc}") from exc
        return self._shape(payload)

    async def _arun(
        self,
        url: str,
        query: str | None = None,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> tuple[str, dict[str, Any]]:
        try:
            payload = await self._async_client().scrape(self._body(url, query))
        except QuanticDataAPIError as exc:
            raise ToolException(f"Scrape failed: {exc}") from exc
        return self._shape(payload)
