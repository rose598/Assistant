"""LLM 接入模块：客户端封装 / Mock 降级 / Prompt 模板 / RAG 引擎。

对外暴露第 3 周核心类型（re-export），供上层 `from src.llm import ...` 使用。
"""

from src.llm.client import (
    LLMCallStats,
    LLMError,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    OpenAILLMClient,
)
from src.llm.embedding import (
    DEFAULT_DIM,
    Embedder,
    MockEmbedder,
    cosine_similarity,
    create_embedder,
)
from src.llm.integrated_qa import AskResult, IntegratedQA, KeywordHit, KeywordMatcher
from src.llm.mock_llm import MockLLMClient, create_llm_client
from src.llm.query_understanding import normalize_query, rewrite_query, understand
from src.llm.rag_engine import RagEngine, create_rag_engine, format_knowledge, source_ids
from src.llm.streaming import first_token_latency, iter_token_text, sse_payload, stream_sse
from src.llm.vector_store import (
    MemoryVectorStore,
    RetrievedChunk,
    VectorStore,
    create_vector_store,
)

__all__ = [
    "DEFAULT_DIM",
    "AskResult",
    "Embedder",
    "IntegratedQA",
    "KeywordHit",
    "KeywordMatcher",
    "LLMCallStats",
    "LLMError",
    "LLMRateLimitError",
    "LLMResponse",
    "LLMTimeoutError",
    "MemoryVectorStore",
    "MockEmbedder",
    "MockLLMClient",
    "OpenAILLMClient",
    "RagEngine",
    "RetrievedChunk",
    "VectorStore",
    "cosine_similarity",
    "create_embedder",
    "create_llm_client",
    "create_rag_engine",
    "create_vector_store",
    "first_token_latency",
    "format_knowledge",
    "iter_token_text",
    "normalize_query",
    "rewrite_query",
    "source_ids",
    "sse_payload",
    "stream_sse",
    "understand",
]
