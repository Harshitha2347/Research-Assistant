from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, List, Optional

from langchain_core.embeddings import Embeddings
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.bridge.pydantic import Field, PrivateAttr

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "models/gemini-embedding-001"
DEFAULT_OUTPUT_DIM = 768 

EMBEDDING_MIN_INTERVAL_SECONDS = float(os.getenv("EMBEDDING_MIN_INTERVAL_SECONDS", "1.0"))

DEFAULT_EMBED_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "100"))

_MAX_RETRIES = int(os.getenv("EMBEDDING_MAX_RETRIES", "6"))
_MAX_BACKOFF_SECONDS = 60.0
_RETRYABLE_MARKERS = ("429", "quota", "rate limit", "resourceexhausted", "503", "unavailable")
_DAILY_QUOTA_MARKERS = ("per day", "daily", "requests per day", "rpd")


def _is_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _RETRYABLE_MARKERS)


def _looks_like_daily_quota(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _DAILY_QUOTA_MARKERS)


class _RateLimiter:

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval


_rate_limiter = _RateLimiter(EMBEDDING_MIN_INTERVAL_SECONDS)


def _embed_batch(
    genai_module: Any,
    texts: List[str],
    *,
    model: str,
    task_type: str,
    output_dimensionality: Optional[int],
) -> List[List[float]]:

    if not texts:
        return []

    def _call(batch: List[str]) -> List[List[float]]:
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            _rate_limiter.wait()
            try:
                result = genai_module.embed_content(
                    model=model,
                    content=batch,
                    task_type=task_type,
                    output_dimensionality=output_dimensionality,
                )
                embedding = result["embedding"]
               
                if embedding and isinstance(embedding[0], (int, float)):
                    embedding = [embedding]
                return embedding
            except Exception as exc:  # noqa: BLE001 - re-raised after retries
                last_exc = exc
                if _looks_like_daily_quota(exc):
                   
                    raise RuntimeError(
                        "Gemini embedding daily quota appears to be "
                        "exhausted for this project. Retrying won't help "
                        "until it resets (midnight Pacific time) — check "
                        "https://aistudio.google.com/rate-limit, or space "
                        "out large uploads across days on the free tier."
                    ) from exc
                if attempt < _MAX_RETRIES - 1 and _is_retryable(exc):
                    logger.warning(
                        "[gemini_embedding] retryable error (attempt %s/%s), "
                        "waiting %.1fs: %s",
                        attempt + 1,
                        _MAX_RETRIES,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
                    delay = min(delay * 2, _MAX_BACKOFF_SECONDS)
                    continue
                raise
        raise last_exc  # pragma: no cover - unreachable

    try:
        return _call(texts)
    except Exception as exc:  # noqa: BLE001
        if len(texts) == 1:
            raise
        logger.warning(
            "[gemini_embedding] batch of %s failed (%s), falling back to per-text calls",
            len(texts),
            exc,
        )
        return [_call([t])[0] for t in texts]


class GeminiEmbedding(BaseEmbedding):


    model_name: str = Field(default=DEFAULT_MODEL)
    api_key: str = Field(default="")
    output_dimensionality: Optional[int] = Field(default=DEFAULT_OUTPUT_DIM)
    doc_task_type: str = Field(default="RETRIEVAL_DOCUMENT")
    query_task_type: str = Field(default="RETRIEVAL_QUERY")

    _genai: Any = PrivateAttr()

    def __init__(
        self,
        api_key: str,
        model_name: str = DEFAULT_MODEL,
        output_dimensionality: Optional[int] = DEFAULT_OUTPUT_DIM,
        embed_batch_size: int = DEFAULT_EMBED_BATCH_SIZE,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            api_key=api_key,
            output_dimensionality=output_dimensionality,
            embed_batch_size=embed_batch_size,
            **kwargs,
        )
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self._genai = genai

    @classmethod
    def class_name(cls) -> str:
        return "GeminiEmbedding"

    # -- sync -----------------------------------------------------------
    def _get_query_embedding(self, query: str) -> List[float]:
        return _embed_batch(
            self._genai,
            [query],
            model=self.model_name,
            task_type=self.query_task_type,
            output_dimensionality=self.output_dimensionality,
        )[0]

    def _get_text_embedding(self, text: str) -> List[float]:
        return _embed_batch(
            self._genai,
            [text],
            model=self.model_name,
            task_type=self.doc_task_type,
            output_dimensionality=self.output_dimensionality,
        )[0]

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return _embed_batch(
            self._genai,
            texts,
            model=self.model_name,
            task_type=self.doc_task_type,
            output_dimensionality=self.output_dimensionality,
        )

    def get_query_embedding_batch(self, queries: List[str]) -> List[List[float]]:
        return _embed_batch(
            self._genai,
            queries,
            model=self.model_name,
            task_type=self.query_task_type,
            output_dimensionality=self.output_dimensionality,
        )

    async def _aget_query_embedding(self, query: str) -> List[float]:
        import asyncio

        return await asyncio.to_thread(self._get_query_embedding, query)

    async def _aget_text_embedding(self, text: str) -> List[float]:
        import asyncio

        return await asyncio.to_thread(self._get_text_embedding, text)


class GeminiLangchainEmbeddings(Embeddings):
    def __init__(
        self,
        api_key: str,
        model_name: str = DEFAULT_MODEL,
        output_dimensionality: Optional[int] = DEFAULT_OUTPUT_DIM,
    ) -> None:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self._genai = genai
        self.model_name = model_name
        self.output_dimensionality = output_dimensionality

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return _embed_batch(
            self._genai,
            texts,
            model=self.model_name,
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=self.output_dimensionality,
        )

    def embed_query(self, text: str) -> List[float]:
        return _embed_batch(
            self._genai,
            [text],
            model=self.model_name,
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=self.output_dimensionality,
        )[0]