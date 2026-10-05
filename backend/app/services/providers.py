from typing import Protocol

import httpx
from fastapi import HTTPException

from app.core.config import get_settings


class LLMClient(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str: ...


class ProviderError(Exception):
    def __init__(self, detail: str, status_code: int = 502):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


async def _post(path: str, key: str, payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(base_url="https://openrouter.ai/api/v1", timeout=30) as client:
            response = await client.post(path, headers={"Authorization": f"Bearer {key}"}, json=payload)
        if response.status_code in (401, 403):
            raise ProviderError("AI provider rejected its credentials", 503)
        if response.status_code == 429:
            raise ProviderError("AI provider rate limit reached", 503)
        if response.status_code >= 400:
            raise ProviderError("AI provider request failed")
        return response.json()
    except httpx.TimeoutException as exc:
        raise ProviderError("AI provider timed out", 504) from exc
    except httpx.RequestError as exc:
        raise ProviderError("AI provider is unavailable", 503) from exc
    except ValueError as exc:
        raise ProviderError("AI provider returned invalid JSON") from exc


class OpenRouterEmbeddingClient:
    def __init__(self, key: str, model: str, dimension: int):
        self.key, self.model, self.dimension = key, model, dimension

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        data = await _post("/embeddings", self.key, {"model": self.model, "input": texts, "dimensions": self.dimension})
        try:
            rows = data["data"]
            if len(rows) != len(texts) or sorted(row["index"] for row in rows) != list(range(len(texts))):
                raise ValueError()
            return [row["embedding"] for row in sorted(rows, key=lambda row: row["index"])]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("AI provider returned invalid embeddings") from exc


class OpenRouterLLMClient:
    def __init__(self, key: str, model: str):
        self.key, self.model = key, model

    async def complete(self, messages: list[dict[str, str]]) -> str:
        data = await _post("/chat/completions", self.key, {"model": self.model, "messages": messages})
        try:
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError()
            return content.strip()
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("AI provider returned an invalid answer") from exc


def get_embedding_client():
    settings = get_settings()
    if settings.embedding_provider.lower() != "openrouter" or not settings.embedding_model or not (settings.embedding_api_key or settings.llm_api_key):
        raise HTTPException(503, "Embedding provider is not configured")
    return OpenRouterEmbeddingClient(settings.embedding_api_key or settings.llm_api_key, settings.embedding_model, settings.embedding_dimension)


def get_llm_client():
    settings = get_settings()
    if settings.llm_provider.lower() != "openrouter" or not settings.llm_model or not settings.llm_api_key:
        raise HTTPException(503, "LLM provider is not configured")
    return OpenRouterLLMClient(settings.llm_api_key, settings.llm_model)
