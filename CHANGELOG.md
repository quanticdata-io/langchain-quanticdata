# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-18

### Added

- `QuanticDataSearch` tool (web search through `/scraper/serp`: organic results and, on Google, the AI Overview when present).
- `QuanticDataScrape` tool (one page to Markdown through `/scraper/extract`, content and artifact).
- `QuanticDataLoader` document loader with `scrape`, `crawl` and `map` modes, sync and async, lazy loading while jobs run.
- `QuanticDataSearchRetriever`: search, then read the top results as Documents, with snippet fallbacks.
- robots.txt checks on the caller's side (RFC 9309) for the loader and the retriever.
- Unit tests with recorded, trimmed API responses and LangChain standard tool tests; no network in tests.
