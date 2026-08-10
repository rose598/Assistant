"""问答主流程 Pipeline。

组装完整问答链路:接收问题 → 意图识别 → 知识库检索 → 回复生成。

当前为 v0.1 基础层实现:
- 意图识别:基于关键词的 IntentEngine
- 知识库检索:KnowledgeMatcher 的模糊匹配 + 关键词精确匹配双通道
- 回复生成:优先返回匹配到的 FAQ 答案;无匹配时回退到意图相关的 FAQ 或提示信息

LLM 兜底,RAG,多轮对话等进阶能力留待后续版本接入(通过
intent_engine.suggest_llm() 标记需要 LLM 处理的查询)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.intent import (
    INTENT_ERROR_DIAGNOSIS,
    INTENT_JOB_STATUS,
    INTENT_JOB_SUBMISSION,
    INTENT_PERMISSION,
    IntentEngine,
    IntentResult,
)
from src.knowledge.loader import KnowledgeLoader, KnowledgeMatcher
from src.knowledge.schema import FAQEntry, KnowledgeBase


@dataclass
class Answer:
    """一次问答的完整结果。"""

    query: str
    answer: str
    intent: IntentResult
    matched_faq: FAQEntry | None = None
    fallback: bool = False  # 是否走了回退逻辑(未精确命中)
    matched_score: float = 0.0
    suggestions: list[str] = field(default_factory=list)  # 供用户进一步操作的建议

    @property
    def needs_llm(self) -> bool:
        """是否需要 LLM 兜底（供上层决策，当前版本不实际调用 LLM）。"""
        return self.intent.is_unknown or len(self.answer) == 0


# 各一级意图对应的兜底引导文案
_FALLBACK_HINTS: dict[str, str] = {
    INTENT_ERROR_DIAGNOSIS: "看起来你在排查某个报错。请尽量附上完整的错误日志和作业 ID，"
    "方便进一步定位。",
    INTENT_JOB_SUBMISSION: "看起来你想提交作业。可以参考知识库中的提交任务、SBATCH 脚本和"
    "交互式会话相关条目。",
    INTENT_JOB_STATUS: "看起来你在查询作业状态。可用 `squeue -u \"$USER\"` 查看，或用"
    " `scontrol show job <job_id>` 查看详情。",
    INTENT_PERMISSION: "看起来你遇到了配额、登录或权限问题。可参考平台资源说明和 QOS 层级"
    "相关条目。",
}


class AnswerPipeline:
    """问答主流程引擎。

    用法::

        pipeline = AnswerPipeline()
        answer = pipeline.ask("如何提交作业")
        print(answer.answer)
    """

    def __init__(
        self,
        kb: KnowledgeBase | None = None,
        matcher: KnowledgeMatcher | None = None,
        intent_engine: IntentEngine | None = None,
    ) -> None:
        if kb is None or matcher is None:
            loader = KnowledgeLoader()
            kb = loader.load()
            matcher = KnowledgeMatcher(kb)
        self._kb = kb
        self._matcher = matcher
        self._intent = intent_engine or IntentEngine()

    def ask(self, query: str) -> Answer:
        """处理单条查询，返回完整回答。"""
        query = (query or "").strip()
        if not query:
            return Answer(
                query=query,
                answer="请输入问题，输入 help 查看帮助。",
                intent=IntentResult(primary=INTENT_ERROR_DIAGNOSIS, is_unknown=True),
                fallback=True,
            )

        # 1. 意图识别
        intent = self._intent.classify(query)

        # 2. 知识库检索:先模糊匹配,再按关键词精确匹配兜底
        matched: FAQEntry | None = None
        score = 0.0
        fuzzy = self._matcher.match(query, top_k=1)
        if fuzzy:
            matched, score = fuzzy[0]

        # 3. 回复生成
        if matched and matched.answer:
            answer_text = matched.answer
            fallback = False
        else:
            # 无精确命中:回退到意图相关的引导文案
            hint = _FALLBACK_HINTS.get(intent.primary, _FALLBACK_HINTS[INTENT_ERROR_DIAGNOSIS])
            answer_text = hint
            fallback = True

        suggestions = self._build_suggestions(matched, intent)

        return Answer(
            query=query,
            answer=answer_text,
            intent=intent,
            matched_faq=matched,
            fallback=fallback,
            matched_score=score,
            suggestions=suggestions,
        )

    def _build_suggestions(
        self, matched: FAQEntry | None, intent: IntentResult
    ) -> list[str]:
        """生成供用户进一步操作的建议列表。"""
        suggestions: list[str] = []
        if matched and matched.related_errors:
            for rel in matched.related_errors:
                suggestions.append(f"相关错误：{rel}")
        if intent.subclasses:
            # 提供用户可能想继续问的方向
            suggestions.append(f"已识别意图：{intent.primary} / {intent.subclasses[0]}")
        return suggestions


__all__ = ["Answer", "AnswerPipeline"]
