"""/api/ask 自然语言问答端点.

对接问答主流程 pipeline (src.pipeline.AnswerPipeline), 返回结构化 JSON:
问题、回答、置信度、意图、命中的 FAQ / 来源.

鲁棒性:
- 空问题 / 过长问题 / 无关问题均有合理返回
- LLM 兜底尚未接入, 当 needs_llm 为真时返回提示
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.pipeline import AnswerPipeline

router = APIRouter(prefix="/api/ask", tags=["ask"])


# ---- 请求/响应模型 ------------------------------------------------------------

class AskRequest(BaseModel):
    """问答请求."""

    question: str = Field(..., min_length=1, max_length=5000, description="用户问题")


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
    intent: IntentInfo
    matched: MatchedInfo | None = None
    sources: list[str] = []
    needs_llm: bool = False


# ---- 单例 pipeline -----------------------------------------------------------

_pipeline: AnswerPipeline | None = None


def get_ask_pipeline() -> AnswerPipeline:
    """懒加载问答 pipeline 单例."""
    global _pipeline
    if _pipeline is None:
        _pipeline = AnswerPipeline()
    return _pipeline


# ---- 端点 --------------------------------------------------------------------

@router.post("", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    """接受自然语言问题, 返回回复 + 意图 + 来源."""
    question = req.question.strip()

    # 空问题(纯空格)友好处理
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空")

    pipe = get_ask_pipeline()
    answer = pipe.ask(question)

    matched = None
    if answer.matched_faq is not None:
        matched = MatchedInfo(
            faq_id=answer.matched_faq.id,
            score=answer.matched_score,
            title=answer.matched_faq.title,
        )

    sources: list[str] = []
    if answer.matched_faq is not None:
        sources = answer.matched_faq.references[:5]

    return AskResponse(
        query=question,
        answer=answer.answer,
        confidence=answer.matched_score / 100.0 if answer.matched_score else (
            0.0 if answer.intent.is_unknown else 0.5
        ),
        intent=IntentInfo(
            primary=answer.intent.primary,
            subclasses=answer.intent.subclasses[:5],
            is_unknown=answer.intent.is_unknown,
            score=answer.intent.score,
        ),
        matched=matched,
        sources=sources,
        needs_llm=answer.needs_llm,
    )


@router.get("/health")
async def ask_health() -> dict[str, str]:
    """问答端点健康检查."""
    return {"status": "ok"}
