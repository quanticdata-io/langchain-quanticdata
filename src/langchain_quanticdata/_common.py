"""Shared pieces of the tools and the retriever: credentials, clients and result shaping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.utils import secret_from_env
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from ._client import API_KEY_ENV, AsyncQuanticDataClient, QuanticDataClient, resolve_base_url

GOOGLE_CLICK_PREFIXES = ("https://www.google.com/url?", "http://www.google.com/url?", "/url?")


class ClientConfig(BaseModel):
    """Credentials and clients, shared by every component that is a pydantic model."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    api_key: SecretStr | None = Field(default_factory=secret_from_env(API_KEY_ENV, default=None))
    """QuanticData API key. Defaults to the ``QUANTICDATA_API_KEY`` environment variable."""

    base_url: str | None = None
    """API base URL. Defaults to ``QUANTICDATA_API_BASE`` or ``https://api.quanticdata.io/v1``."""

    client: QuanticDataClient | None = Field(default=None, exclude=True)
    """Pre-built synchronous client (optional)."""

    async_client: AsyncQuanticDataClient | None = Field(default=None, exclude=True)
    """Pre-built asynchronous client (optional)."""

    @model_validator(mode="after")
    def _check_credentials(self) -> ClientConfig:
        if self.client is None and self.async_client is None and self.api_key is None:
            raise ValueError(
                f"No QuanticData API key: pass api_key=... or set {API_KEY_ENV}. "
                "Keys are created on the API keys page of the QuanticData dashboard."
            )
        return self

    def _key(self) -> str | None:
        return self.api_key.get_secret_value() if self.api_key is not None else None

    def _sync_client(self) -> QuanticDataClient:
        if self.client is None:
            self.client = QuanticDataClient(self._key(), base_url=resolve_base_url(self.base_url))
        return self.client

    def _async_client(self) -> AsyncQuanticDataClient:
        if self.async_client is None:
            self.async_client = AsyncQuanticDataClient(self._key(), base_url=resolve_base_url(self.base_url))
        return self.async_client


def is_click_url(link: str) -> bool:
    """True for a search engine's click address, which does not lead to the page when fetched."""
    return link.startswith(GOOGLE_CLICK_PREFIXES)


def organic_results(payload: Mapping[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
    """Organic results reduced to the fields a model needs, in rank order."""
    out: list[dict[str, Any]] = []
    for row in payload.get("organic") or []:
        if not isinstance(row, Mapping) or not row.get("link"):
            continue
        item: dict[str, Any] = {
            "rank": row.get("rank"),
            "title": row.get("title"),
            "url": row.get("link"),
            "snippet": row.get("description"),
        }
        for key in ("source", "date"):
            if row.get(key):
                item[key] = row[key]
        out.append(item)
        if limit is not None and len(out) >= limit:
            break
    return out
