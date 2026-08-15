"""/api/ask 自然语言问答端点（双通道接入）.

对接双通道问答 ``IntegratedQA``（第 3 周 Day 4）：
- 关键词通道：命中且置信度足够 -> 直接知识库直回（省 LLM 调用）。
- RAG + LLM 通道：未命中 / 低置信 -> 检索 + LLM 兜底生成（真实 qwen / mock 自动降级）。
- 多轮会话：``session_id`` 隔离并累积历史（SessionStore 内存实现，可换 Redis）。
- `/api/ask/stream`：SSE 流式逐 token 输出。

响应向后兼容：保留旧字段 ``intent``（对象）/ ``matched`` / ``sources`` / ``needs_llm``，
新增 ``channel``（keyword / rag / fallback）。

鲁棒性：
- 空问题 / 过长 / 无关问题均有合理返回（不 500）。
- LLM 未配置 / 构造异常 -> 降级：mock 或关键词-only，不抛给端点。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import src.llm.mock_llm as mock_llm
from src.dialog.store import create_session_store
from src.llm.integrated_qa import AskResult, IntegratedQA, KeywordHit, KeywordMatcher
from src.pipeline import AnswerPipeline

router = APIRouter(prefix="/api/ask", tags=["ask"])


# ---- 请求/响应模型 ------------------------------------------------------------

class AskRequest(BaseModel):
    """问答请求."""

    question: str = Field(..., min_length=1, max_length=5000, description="用户问题")
    session_id: str = Field("", max_length=200, description="会话 ID（多轮对话用）")


class IntentInfo(BaseModel):
    """意图信息."""

    primary: str
    subclasses: list[str]
    is_unknown: bool
    score: float


class MatchedInfo(BaseModel):
    """命中的 FAQ 信息."""

    faq_id: str
    score: float
    title: str


class AskResponse(BaseModel):
    """问答响应."""

    query: str
    answer: str
    confidence: float
    channel: str  # keyword / rag / fallback
    intent: IntentInfo
    matched: MatchedInfo | None = None
    sources: list[str] = []
    needs_llm: bool = False


# ---- 关键词通道适配器 ---------------------------------------------------------

class PipelineKeywordAdapter:
    """把现有 ``AnswerPipeline`` 适配为 ``IntegratedQA.keyword_matcher``.

    ``AnswerPipeline.ask`` 返回 ``Answer``（含 matched_faq / matched_score / intent），
    这里转成双通道协议要求的 ``KeywordHit``；未命中（无 FAQ）时返回 None，
    交给双通道回退到 RAG/LLM。
    """

    def __init__(self, pipeline: AnswerPipeline) -> None:
        self._pipeline = pipeline

    def match(self, query: str) -> KeywordHit | None:
        answer = self._pipeline.ask(query)
        if answer.matched_faq is None:
            return None
        confidence = answer.matched_score / 100.0 if answer.matched_score else 0.0
        sources = answer.matched_faq.references[:5]
        return KeywordHit(
            answer=answer.answer,
            confidence=confidence,
            intent=answer.intent.primary,
            sources=sources,
        )


# ---- 装配 ---------------------------------------------------------------------

_qa: IntegratedQA | None = None


def _build_llm(config: object | None = None) -> object | None:
    """构造 LLM 客户端；异常时降级为 None（关键词-only），不抛给端点。

    通过模块属性访问 ``create_llm_client``，便于测试 monkeypatch 该工厂。
    """
    try:
        return mock_llm.create_llm_client(config)
    except Exception:
        return None


def _build_qa() -> IntegratedQA:
    """构造双通道问答装配点（含关键词适配器 / 会话存储 / LLM 自动降级）。"""
    pipeline = AnswerPipeline()
    keyword_matcher: KeywordMatcher = PipelineKeywordAdapter(pipeline)
    session_store = create_session_store()
    llm = _build_llm(None)
    return IntegratedQA(
        keyword_matcher=keyword_matcher,
        llm=llm,
        session_store=session_store,
    )


def get_qa() -> IntegratedQA:
    """懒加载双通道问答单例."""
    global _qa
    if _qa is None:
        _qa = _build_qa()
    return _qa


def _to_ask_response(
    query: str, result: AskResult, matched: MatchedInfo | None
) -> AskResponse:
    """把 AskResult 转成向后兼容的 AskResponse（intent 对象等旧字段）。"""
    return AskResponse(
        query=query,
        answer=result.answer,
        confidence=result.confidence,
        channel=result.channel,
        intent=IntentInfo(
            primary=result.intent,
            subclasses=[],
            is_unknown=result.intent == "unknown",
            score=result.confidence,
        ),
        matched=matched,
        sources=result.sources,
        needs_llm=result.needs_llm,
    )


# ---- 端点 --------------------------------------------------------------------

@router.post("", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    """接受自然语言问题, 返回回复 + 意图 + 来源 (双通道)."""
    question = req.question.strip()

    # 空问题(纯空格)友好处理
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空")

    qa = get_qa()
    result = await qa.ask(req.session_id, question)

    matched = None
    if result.channel == "keyword" and result.sources:
        # 旧字段 matched 仅当关键词命中知识库时有值（保持兼容）
        matched = MatchedInfo(
            faq_id=result.sources[0],
            score=result.confidence * 100.0,
            title=result.sources[0],
        )

    return _to_ask_response(question, result, matched)


@router.post("/stream")
async def ask_stream(req: AskRequest) -> StreamingResponse:
    """SSE 流式问答：逐 token 输出（keyword 直回 / RAG 逐步）. """
    question = req.question.strip()
    if not question:
        return StreamingResponse(
            _empty_stream(), media_type="text/event-stream"
        )

    qa = get_qa()
    return StreamingResponse(
        _sse_stream(qa, req.session_id, question),
        media_type="text/event-stream",
    )


async def _empty_stream():
    """空问题的流式收尾."""
    yield "data: [DONE]\n\n"


async def _sse_stream(qa: IntegratedQA, session_id: str, question: str):
    """消费集成问答的流式产出, 包装为 SSE 帧."""
    from src.llm.streaming import sse_payload

    try:
        async for token in qa.ask_stream(session_id, question):
            yield sse_payload({"type": "token", "content": token})
    except Exception as exc:
        yield sse_payload({"type": "error", "message": str(exc)})
    yield "data: [DONE]\n\n"


@router.get("/health")
async def ask_health() -> dict[str, str]:
    """问答端点健康检查."""
    return {"status": "ok"}
