"""A LangChain agent that searches the web and reads pages with the QuanticData tools.

    export QUANTICDATA_API_KEY=your-key
    pip install langchain langchain-anthropic        # or the integration of your model provider
    export AGENT_MODEL="anthropic:<model-name>"     # any "provider:model" string init_chat_model accepts
    python examples/agent.py "What is retrieval augmented generation? Cite two sources."

The model provider's own key (for example ``ANTHROPIC_API_KEY``) must be set as well.
"""

from __future__ import annotations

import os
import sys

from langchain_quanticdata import QuanticDataScrape, QuanticDataSearch


def main(question: str) -> None:
    from langchain.agents import create_agent  # type: ignore[import-not-found]

    model = os.environ.get("AGENT_MODEL")
    if not model:
        sys.exit('Set AGENT_MODEL to a "provider:model" string, for example "anthropic:<model-name>".')
    tools = [
        QuanticDataSearch(engine="bing", max_results=5, country="us"),
        QuanticDataScrape(max_tokens=4000),
    ]
    agent = create_agent(model, tools=tools)
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]) or "What is retrieval augmented generation? Cite two sources.")
