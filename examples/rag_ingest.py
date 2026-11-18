"""Crawl a public sample site into Markdown Documents and split them into chunks for a vector store.

    export QUANTICDATA_API_KEY=your-key
    python examples/rag_ingest.py

Needs ``langchain-text-splitters`` (``pip install langchain-text-splitters``). The crawl is billed
up front on ``limit`` pages and the unfetched pages are refunded: keep the limit small while you try it.
"""

from __future__ import annotations

from langchain_quanticdata import QuanticDataLoader


def main() -> None:
    from langchain_text_splitters import MarkdownHeaderTextSplitter  # type: ignore[import-not-found]

    loader = QuanticDataLoader(
        "https://quotes.toscrape.com/",
        mode="crawl",
        limit=5,
        depth=1,
        exclude=["/login"],
    )
    splitter = MarkdownHeaderTextSplitter([("#", "h1"), ("##", "h2")])
    chunks = 0
    for doc in loader.lazy_load():
        for chunk in splitter.split_text(doc.page_content):
            chunk.metadata.update(doc.metadata)
            chunks += 1
        print(f"{doc.metadata['source']}  depth={doc.metadata.get('depth')}  chars={len(doc.page_content)}")
    print(f"{chunks} chunks")


if __name__ == "__main__":
    main()
