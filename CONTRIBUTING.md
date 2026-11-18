# Contributing

Thanks for helping improve the LangChain integration.

## Setup

```bash
git clone https://github.com/quanticdata-io/langchain-quanticdata
cd langchain-quanticdata
uv venv && uv pip install -e . --group dev
```

Plain pip works too: `pip install -e . pytest pytest-asyncio pytest-cov pytest-socket langchain-tests mypy ruff`.

## Checks

CI runs these on Python 3.11 to 3.13, on Ubuntu and Windows, plus the tests against the lowest supported `langchain-core`:

```bash
ruff check .
ruff format --check .
mypy
pytest
```

## Ground rules

- Tests never call the QuanticData API or a website. `pytest-socket` is set to allow loopback only, so a test that tries fails. Use `MockApi` and `robots()` from `tests/helpers.py`.
- Fixtures in `tests/fixtures/` are API responses recorded on public sample sites and public search results, trimmed, wrapped in the documented envelope and stripped of ids, tokens and anything personal. Keep new ones the same way.
- Send only parameters documented in the [QuanticData API reference](https://quanticdata.io/docs/). New options arrive through `extra_params` / `params` first.
- Follow LangChain conventions: tools subclass `BaseTool` with a pydantic `args_schema`, the loader implements `lazy_load` and `alazy_load`, the retriever implements `_get_relevant_documents` and `_aget_relevant_documents`.
- User-facing changes need a CHANGELOG entry under "Unreleased".

## Running against the real API

```bash
export QUANTICDATA_API_KEY=your-key
python examples/search_retriever.py "what is retrieval augmented generation"
python examples/rag_ingest.py
```

These calls are billed to your account (see https://quanticdata.io/pricing/).
