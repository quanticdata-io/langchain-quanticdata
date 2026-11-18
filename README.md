# langchain-quanticdata

LangChain tools, a document loader and a retriever for the [QuanticData](https://quanticdata.io/) web data API: search the web, read pages as Markdown, and load single pages, whole sites (crawl) or a site's URL list (sitemaps and links) as LangChain `Document`s.

[![CI](https://github.com/quanticdata-io/langchain-quanticdata/actions/workflows/ci.yml/badge.svg)](https://github.com/quanticdata-io/langchain-quanticdata/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

| Component | LangChain base class | API endpoint |
| --- | --- | --- |
| `QuanticDataSearch` | `BaseTool` | `POST /scraper/serp` (Google, Bing or DuckDuckGo) |
| `QuanticDataScrape` | `BaseTool` | `POST /scraper/extract` |
| `QuanticDataLoader` | `BaseLoader` | `/scraper/extract`, `/scraper/crawl`, `/scraper/map` + `/scraper/batch` |
| `QuanticDataSearchRetriever` | `BaseRetriever` | `/scraper/serp`, then `/scraper/extract` per result |

Everything has a sync and an async path. The only dependencies are `langchain-core` (1.x) and `httpx`.

## Install

The package is not on PyPI yet. Install it from source:

```bash
pip install git+https://github.com/quanticdata-io/langchain-quanticdata
```

or from a clone:

```bash
git clone https://github.com/quanticdata-io/langchain-quanticdata
cd langchain-quanticdata
pip install -e .
```

Python 3.11 or later (the minimum of `langchain-core` 1.x). Then set your API key, created on the API keys page of the QuanticData dashboard:

```bash
export QUANTICDATA_API_KEY=your-key
```

Every call is billed to that account; see [pricing](https://quanticdata.io/pricing/).

## Quickstart

```python
from langchain_quanticdata import QuanticDataSearch, QuanticDataScrape

search = QuanticDataSearch(engine="bing", max_results=3, country="us")
print(search.invoke({"query": "what is retrieval augmented generation"}))
```

Output of that call on 18 November 2026 (snippets shortened):

```python
{
    "query": "what is retrieval augmented generation",
    "results": [
        {
            "rank": 1,
            "title": "What is Retrieval-Augmented Generation (RAG) - GeeksforGeeks",
            "url": "https://www.geeksforgeeks.org/nlp/what-is-retrieval-augmented-generation-rag/",
            "snippet": "Retrieval-Augmented Generation (RAG) is a way to make AI answers ...",
            "source": "geeksforgeeks.org",
            "date": "May 1, 2026",
        },
        {
            "rank": 2,
            "title": "What is Retrieval Augmented Generation (RAG)? | Databricks",
            "url": "https://www.databricks.com/blog/what-is-retrieval-augmented-generation",
            "snippet": "Retrieval augmented generation is an AI pattern that ...",
            "source": "databricks.com",
        },
        {
            "rank": 3,
            "title": "Retrieval-augmented generation - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
            "snippet": "Retrieval-augmented generation (RAG) is a technique that ...",
            "source": "en.wikipedia.org",
        },
    ],
}
```

Read a page:

```python
scrape = QuanticDataScrape(max_tokens=2000)
print(scrape.invoke({"url": "https://quotes.toscrape.com/"}))
```

```text
# [Quotes to Scrape](https://quotes.toscrape.com/)

[Login](https://quotes.toscrape.com/login)

“The world as we have created it is a process of our thinking. It cannot be changed without changing our thinking.” by Albert Einstein [(about)](https://quotes.toscrape.com/author/Albert-Einstein)
...
```

Give both tools to an agent ([`examples/agent.py`](examples/agent.py)):

```python
from langchain.agents import create_agent

agent = create_agent("provider:model-name", tools=[search, scrape])
agent.invoke({"messages": [{"role": "user", "content": "What is RAG? Cite two sources."}]})
```

## Tools

### `QuanticDataSearch`

Model input: `query` (string). Output: a dict with `query`, `results` (each with `rank`, `title`, `url`, `snippet` and, when present, `source` and `date`) and, on Google, `ai_overview` and `ai_overview_references` when the results page carried an AI Overview that the API returned. Many queries have none; the key is then absent.

| Option | Default | Meaning |
| --- | --- | --- |
| `engine` | `"google"` | `google`, `bing` or `duckduckgo` |
| `num` | `10` | Results to request (1 to 100) |
| `max_results` | `None` | Keep at most this many results in the output |
| `country` | `None` | Country code to search from (`us`, `de`...) |
| `lang` | `None` | Interface language (`en`, `it`...) |
| `location` | `None` | Human-readable location, for example `"Milan, Italy"` |
| `device` | `None` | `desktop`, `mobile`, `ios` or `android` |
| `include_ai_overview` | `True` | Return the AI Overview fields when present |
| `extra_params` | `{}` | Any other documented `/scraper/serp` parameter, sent as is (for example `{"safe": "active"}`) |

On Google, a result's `url` can be Google's click address (`https://www.google.com/url?...`) rather than the page's own URL; the API documents this. Bing results carry the page URLs.

### `QuanticDataScrape`

Model input: `url` and an optional `query` (keeps only the sections of the page relevant to it). `response_format="content_and_artifact"`: the tool message content is the page text, and its `artifact` holds `url`, `final_url`, `status`, `title`, `engine` and the page `metadata`. When the page answers 400 or more, is blocked, or needs JavaScript and came back empty, the tool returns an error message to the agent instead of raising (`handle_tool_error=True`).

| Option | Default | Meaning |
| --- | --- | --- |
| `format` | `"markdown"` | `markdown`, `text` or `html` |
| `content_mode` | `"smart"` | `smart` (page without navigation, footer and cookie banners), `article` (main article), `full` (whole body) |
| `engine` | `"auto"` | `auto`, `tls`, `fetch` or `render` (always a headless browser) |
| `render` | `False` | Force a headless browser render; billed at the render rate |
| `max_tokens` | `8000` | Cap the output at about this many tokens, cut at a section boundary; `None` for no cap |
| `links_mode` | `None` | `inline`, `footnote` or `strip` |
| `images_mode` | `None` | `inline`, `alt` or `strip` |
| `country` | `None` | Country code of the exit used for the fetch |
| `extra_params` | `{}` | Any other documented `/scraper/extract` parameter (for example `{"waitForSelector": "#main"}`) |

Both tools also take `api_key` (default `QUANTICDATA_API_KEY`), `base_url` (default `QUANTICDATA_API_BASE` or `https://api.quanticdata.io/v1`), and prebuilt `client` / `async_client`.

## Document loader

```python
from langchain_quanticdata import QuanticDataLoader

# One or more pages
docs = QuanticDataLoader(["https://quotes.toscrape.com/", "https://books.toscrape.com/"]).load()

# A crawl from a seed URL, yielded page by page while the job runs
loader = QuanticDataLoader(
    "https://quotes.toscrape.com/", mode="crawl", limit=10, depth=1, exclude=["/login"]
)
for doc in loader.lazy_load():
    print(doc.metadata["source"], doc.metadata["depth"])

# The site's URL list (sitemaps and homepage links), filtered, then fetched as one batch job
loader = QuanticDataLoader(
    "https://books.toscrape.com/", mode="map", include=["/catalogue/category/"], limit=20
)
print(loader.map_urls())  # see what would be fetched, without fetching it
docs = loader.load()
```

| Mode | Calls | Notes |
| --- | --- | --- |
| `scrape` (default) | `POST /scraper/extract` per URL | `alazy_load` runs `concurrency` requests at a time |
| `crawl` | `POST /scraper/crawl`, then `GET /scraper/crawl/{id}` with `since` until the job ends | Breadth-first from the seed; billed up front on `limit` pages, unfetched pages refunded when the job settles |
| `map` | `POST /scraper/map`, then `POST /scraper/batch` and `GET /scraper/batch/{id}` | Map returns URLs only; the batch fetches them |

Each `Document` has the page text as `page_content` and `metadata` with `source` (the URL), `title`, `status`, `mode`, and when the API returns them `final_url`, `engine`, `depth` (crawl), `job_id` (crawl and map), `description`, `language`, `canonical`, `publishedTime` and `author`.

| Argument | Default | Meaning |
| --- | --- | --- |
| `url` | required | One URL, or a list for `scrape`; `crawl` and `map` take one seed URL |
| `mode` | `"scrape"` | `scrape`, `crawl` or `map` |
| `format` | `"markdown"` | `markdown`, `text` or `html` |
| `content_mode` | `"smart"` | `smart`, `article` or `full` |
| `render` | `False` | Render every page in a headless browser (render rate) |
| `country` | `None` | Country code of the exit |
| `limit` | `50` | `crawl`: maximum pages (API cap 500). `map`: maximum URLs fetched (API cap 5000); with `include`/`exclude` set, the map step asks for up to 5000 URLs and `limit` applies after filtering |
| `depth` | `3` | `crawl`: maximum link depth (API cap 10) |
| `include` / `exclude` | `None` | URL substrings, or globs when they contain `*` (`crawl` and `map`) |
| `search` | `None` | `map`: only URLs containing this substring |
| `include_subdomains` | `False` | `crawl` and `map`: also cover subdomains of the seed host |
| `concurrency` | `5` | `map`: simultaneous fetches of the batch job (1 to 20); `scrape` with `alazy_load`: simultaneous requests |
| `respect_robots` | `True` | Check each site's robots.txt on your side (see below) |
| `robots_user_agent` | `"*"` | User agent whose robots.txt group applies |
| `continue_on_failure` | `True` | Skip failed pages with a logged warning; `False` raises `QuanticDataJobError`. 401, 402 and 403 from the API always raise |
| `poll_interval` | `2.0` | Seconds between job polls |
| `timeout` | `900.0` | Seconds before a running job is given up (`QuanticDataJobError`) |
| `params` | `None` | Extra documented API parameters merged into the request body |
| `api_key`, `base_url`, `client`, `async_client`, `robots` | | Credentials, endpoints and prebuilt clients |

Splitting for a vector store is left to LangChain's text splitters; [`examples/rag_ingest.py`](examples/rag_ingest.py) crawls a sample site and splits it by Markdown headings.

## Retriever

```python
from langchain_quanticdata import QuanticDataSearchRetriever

retriever = QuanticDataSearchRetriever(k=3, country="us", max_tokens=2000)
for doc in retriever.invoke("what is retrieval augmented generation"):
    print(doc.metadata["rank"], doc.metadata["source"], doc.metadata["fetched"])
```

It searches, takes the top `k` results and reads each page. A result comes back as its search snippet instead, with `metadata["fetched"]` saying why, when the URL is a search engine click address (`snippet:click-url`), robots.txt disallows the page (`snippet:robots`), or the fetch failed (`snippet:fetch-failed`). Read pages have `fetched="page"`.

| Option | Default | Meaning |
| --- | --- | --- |
| `k` | `3` | Results to return (1 to 20) |
| `engine` | `"bing"` | Bing by default because its results carry page URLs; Google results can carry click addresses that cannot be read |
| `country`, `lang`, `location` | `None` | Search (and fetch) settings |
| `fetch_pages` | `True` | `False` returns snippets only: one API call per query |
| `content_mode` | `"smart"` | Content scope of each page |
| `max_tokens` | `4000` | Cap per page; `None` for no cap |
| `focus_on_query` | `False` | Keep only the sections of each page relevant to the query |
| `respect_robots` | `True` | Do not fetch pages robots.txt disallows |

## robots.txt and responsible use

The QuanticData API reference does not document robots.txt handling for crawl, map or batch jobs, so this package checks it on your side. With `respect_robots=True` (the default) the loader and the retriever read each site's `/robots.txt` directly from the site, following RFC 9309 (longest match wins, `*` and `$` patterns; a 4xx robots.txt means no restrictions; a 5xx or an unreachable robots.txt means the site is treated as disallowed), and:

- `scrape` mode and the retriever skip disallowed URLs before calling the API;
- `map` mode drops disallowed URLs before it starts the batch job;
- `crawl` mode refuses a disallowed seed, adds the `Disallow` paths of the applicable group to the crawl's `exclude` list, and drops any returned page the rules disallow. The crawl itself runs on the API side, so a rule that the `exclude` substrings cannot express exactly can still let the crawler fetch a page that is then dropped here. Keep `limit` and `depth` low and use `include`/`exclude` to stay inside the part of the site you need.

Beyond robots.txt: collect only what you are allowed to, respect each site's terms, do not collect personal data you have no lawful basis to process, and keep volumes reasonable. The examples use public sample sites (`quotes.toscrape.com`, `books.toscrape.com`) and public search results.

## Limits

- The package wraps a paid API: nothing works without a key, and each call is billed (search per query, scrape per page, crawl up front on `limit`, batch up front per URL with refunds for failures).
- Only a subset of the API is exposed as typed options. Other documented parameters go through `extra_params` (tools) or `params` (loader); collectors, datasets and the Web Unlocker are not wrapped here.
- Pages that need a login or an interactive step are out of scope.
- Crawl and batch jobs are kept by the API for about an hour after they finish. The loader reads a job while it runs and has no option to reattach to an existing job id.
- 429 answers are retried only when `Retry-After` is 30 seconds or less (twice by default); otherwise `QuanticDataAPIError` is raised with the status and the API message.

## Errors

| Exception | When |
| --- | --- |
| `ValueError` | No API key at construction, or invalid loader arguments |
| `QuanticDataAPIError` | The API answered with an error status; `.status`, `.message` and `.payload` carry the details (for example 402 when the balance cannot cover the call) |
| `QuanticDataJobError` | A crawl or batch job failed, was cancelled or timed out, a crawl seed is disallowed by robots.txt, or a page failed with `continue_on_failure=False` |

The tools turn these into an error message for the agent (`handle_tool_error=True`); set `handle_tool_error=False` to have them raise.

## Running against the real API

Unit tests never use the network. To try the real API, set the key and run the examples:

```bash
export QUANTICDATA_API_KEY=your-key
python examples/search_retriever.py "what is retrieval augmented generation"
python examples/rag_ingest.py            # needs: pip install langchain-text-splitters
python examples/agent.py                 # needs: pip install langchain and your model provider's package
```

`QUANTICDATA_API_BASE` points the package at another API base URL.

## Development

```bash
uv venv && uv pip install -e . --group dev
ruff check . && ruff format --check . && mypy && pytest
```

The tests use `httpx.MockTransport` with API responses recorded on 18 November 2026 on public sample sites and public search results, trimmed and stripped of ids and tokens (`tests/fixtures/`), plus LangChain's standard tool unit tests (`langchain-tests`). `pytest-socket` allows loopback only, so a test that reaches the network fails. See [CONTRIBUTING.md](CONTRIBUTING.md).

API reference: https://quanticdata.io/docs/

## License

[MIT](LICENSE)
