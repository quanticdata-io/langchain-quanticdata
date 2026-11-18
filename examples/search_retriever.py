"""Use the live web as a retriever: search, then read the top results as Markdown.

export QUANTICDATA_API_KEY=your-key
python examples/search_retriever.py "what is retrieval augmented generation"
"""

from __future__ import annotations

import sys

from langchain_quanticdata import QuanticDataSearchRetriever


def main(query: str) -> None:
    retriever = QuanticDataSearchRetriever(k=3, country="us", max_tokens=2000, focus_on_query=True)
    for doc in retriever.invoke(query):
        meta = doc.metadata
        print(f"#{meta['rank']} {meta['title']}")
        print(f"  {meta['source']}  ({meta['fetched']}, {len(doc.page_content)} chars)")


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]) or "what is retrieval augmented generation")
