"""LLM 辅助日志分类 + 规则/LLM 双重判断（规则优先）。

第 4 周周一 A 交付物②（架构见 docs/log-classifier-architecture.md）：
- **规则优先**：先走 ``ErrorClassifier``（毫秒级）；命中且置信度高直接返回，不调 LLM。
- **LLM 兜底**：规则未命中 / 低置信时，把作业诊断上下文送入 LLM，让 LLM 判断类别，
  提升对"新报错、长错误栈、未列入规则的文本"的覆盖率。
- **优雅降级**：LLM 未配置 / 调用失败 / 返回非法类别时，回退到纯规则结果，不劣化、不 500。

面向 plan §3.5 三类十子类，但**不重复实现分类逻辑**（规则细节归 B），
只把规则引擎输出的 ``ErrorClassification`` 作为稳定接口消费，规则不足时用 LLM 补。

典型用法（异步接真实 qwen / mock 自动降级）::

    from src.log_analysis.llm_log_classifier import DualLogClassifier
    dc = DualLogClassifier()
    result = await dc.aclassify(record)   # -> ErrorClassification
    print(result.category, result.subtype, result.confidence, result.signals_hit)

同步用法（无网络 / 测试）::

    result = dc.classify(record)
"""

from __future__ import annotations

import json
from typing import Any

from src.config import get_config
from src.llm.client import LLMClientProtocol
from src.llm.mock_llm import create_llm_client
from src.log_analysis.classifier import (
    SUBTYPE_CATEGORY,
    ErrorClassification,
    ErrorClassifier,
)
from src.log_analysis.commands import JobRecord

# 所有合法子类（白名单，供 LLM 输出校验与非法值兜底）
_VALID_SUBTYPES = frozenset(SUBTYPE_CATEGORY.keys())

# 默认阈值（Config 可配）
_DEFAULT_RULE_CONF_THRESHOLD = 0.6  # 规则置信度 ≥ 此值直接返回，不再调 LLM
_DEFAULT_LLM_CONF_THRESHOLD = 0.5  # LLM 分类置信度 < 此值视为不可靠，回退规则


class LLMLogClassifier:
    """基于 LLM 的日志辅助分类器。

    输入作业记录（reason / exit_code / job_name 等），构造受控 JSON 提示词，
    让 LLM 输出 ``{"category", "subtype", "confidence", "signals_hit"}``，
    再映射回 ``ErrorClassification``。只负责"LLM 这一环"，组合逻辑在
    ``DualLogClassifier``。
    """

    def __init__(
        self,
        llm: LLMClientProtocol | None = None,
        threshold: float | None = None,
        subject: str | None = None,
    ) -> None:
        # subject 兼容旧签名（未用），保留以对齐未来 B 的判定器接口
        self._threshold = (
            threshold if threshold is not None
            else _llm_conf_threshold()
        )
        self._llm = llm if llm is not None else create_llm_client()

    # ---- LLM 调用 ----
    def _build_prompt(self, record: JobRecord) -> list[dict[str, str]]:
        """构造分类提示词（受控 JSON 输出）。"""
        reason = (record.reason or "").strip() or "(无 Reason)"
        err_ctx = f"{record.workdir or ''} {record.command or ''}".strip()
        allowed = "\n".join(sorted(_VALID_SUBTYPES))
        system = (
            "你是中国科学技术大学 107 算力平台的日志分类助手。"
            "你只把日志/作业信息归入给定类目，输出严格 JSON。"
        )
        user = (
            "根据作业信息判断失败原因类别，仅输出 JSON：\n"
            "{"
            '\"category\": 大类(oom|script|env|permission), '
            '\"subtype\": 子类(见白名单), '
            '\"confidence\": 0到1数字, '
            '\"signals_hit\": [命中的特征文本数组]'
            "}\n"
            "子类白名单：\n" + allowed + "\n\n"
            "作业信息：\n"
            f"- 状态: {record.job_state or '未知'}\n"
            f"- Reason: {reason}\n"
            f"- 退出码: {record.exit_code or '未知'}\n"
            f"- 命令/路径: {err_ctx or '未知'}\n"
            "如果无法归类，subtype 请输出 unknown。"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _parse(text: str) -> dict[str, Any] | None:
        """从 LLM 文本中提取 JSON 对象；失败返回 None。"""
        if not text:
            return None

        def _as_dict(raw: Any) -> dict[str, Any] | None:
            return raw if isinstance(raw, dict) else None

        # 尝试直接 JSON
        try:
            parsed = _as_dict(json.loads(text))
            if parsed is not None:
                return parsed
        except Exception:
            pass
        # 尝试提取第一个 {...} 块（LLM 可能夹杂解释）
        start = text.find("{")
        end = text.rfind("}")
        if 0 <= start < end:
            try:
                return _as_dict(json.loads(text[start : end + 1]))
            except Exception:
                return None
        return None

    def _validate(self, data: dict[str, Any] | None) -> tuple[str, str, float, list[str]]:
        """把解析结果规整为 (category, subtype, confidence, signals)；非法值回退 unknown。"""
        if not data:
            return ("unknown", "unknown", 0.0, [])
        subtype = str(data.get("subtype") or "").strip()
        category = str(data.get("category") or "")
        try:
            conf = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
        except (TypeError, ValueError):
            conf = 0.0
        signals = data.get("signals_hit", [])
        if not isinstance(signals, list):
            signals = [str(signals)]
        signals = [str(s) for s in signals if str(s).strip()]
        if subtype not in _VALID_SUBTYPES:
            # 类别非法：不硬猜，交回规则兜底
            return ("unknown", "unknown", 0.0, signals)
        if category not in SUBTYPE_CATEGORY.values():
            category = SUBTYPE_CATEGORY[subtype]
        return (category, subtype, conf, signals)

    # ---- 组装结果 ----
    def _build_result(
        self,
        record: JobRecord,
        category: str,
        subtype: str,
        confidence: float,
        signals: list[str],
    ) -> ErrorClassification:
        # 给 LLM 来源的命中共加 "LLM:" 前缀, 便于 API/调用方区分规则 vs LLM 判定
        prefixed = [f"LLM:{s}" for s in signals] if signals else [f"LLM分类[{subtype}]"]
        return ErrorClassification(
            record=record,
            category=category,
            subtype=subtype,
            confidence=confidence,
            signals_hit=prefixed,
        )

    def classify(self, record: JobRecord) -> ErrorClassification:
        """同步分类。真实 LLM/本仓库 Mock 均为异步，同步调用自动回退 unknown；
        仅注入同步测试替身可真正走 LLM（见单测）。生产请用 ``aclassify``。"""
        try:
            resp = self._llm.complete(self._build_prompt(record))
            # 异步实现返回协程：同步环境下不能 await，视为"不可用"
            if hasattr(resp, "__await__"):
                return self._build_result(record, "unknown", "unknown", 0.0, [])
        except Exception:
            return self._build_result(record, "unknown", "unknown", 0.0, [])
        data = self._parse(getattr(resp, "text", ""))
        cat, sub, conf, signals = self._validate(data)
        return self._build_result(record, cat, sub, conf, signals)

    async def aclassify(self, record: JobRecord) -> ErrorClassification:
        """异步分类（接真实 LLM 的主路径）。"""
        try:
            messages = self._build_prompt(record)
            resp = await self._llm.complete(messages)
        except Exception:
            return self._build_result(record, "unknown", "unknown", 0.0, [])
        data = self._parse(getattr(resp, "text", ""))
        cat, sub, conf, signals = self._validate(data)
        return self._build_result(record, cat, sub, conf, signals)


class DualLogClassifier:
    """规则优先 + LLM 兜底的双重判断门面。

    - 规则命中且置信度 ≥ ``rule_conf_threshold`` → 直接返回规则结果（不调 LLM）。
    - 否则调 LLM；LLM 给出合法且置信度足够的结果 → 用之；
    - 否则/LLM 不可用 → 回退规则原始结果。
    """

    def __init__(
        self,
        rule_engine: ErrorClassifier | None = None,
        llm_classifier: LLMLogClassifier | None = None,
        rule_conf_threshold: float | None = None,
    ) -> None:
        self._rule = rule_engine or ErrorClassifier()
        self._llm_cls = llm_classifier or LLMLogClassifier()
        self._rule_threshold = (
            rule_conf_threshold if rule_conf_threshold is not None
            else _rule_conf_threshold()
        )
        # 统计：命中走 LLM 的次数 / 总调用（用于覆盖率 AC）
        self.llm_calls = 0

    def _needs_llm(self, rule: ErrorClassification) -> bool:
        """规则是否需要 LLM 兜底：未命中 或 置信度 < 阈值。"""
        if not rule.is_known:
            return True
        return float(rule.confidence) < self._rule_threshold

    def classify(self, record: JobRecord) -> ErrorClassification:
        """同步双重判断（规则优先；LLM 仅覆盖规则盲区）。"""
        rule = self._rule.classify(record)
        if not self._needs_llm(rule):
            return rule
        self.llm_calls += 1
        llm = self._llm_cls.classify(record)
        if llm.is_known and llm.confidence >= self._llm_cls._threshold:
            return llm
        return rule

    async def aclassify(self, record: JobRecord) -> ErrorClassification:
        """异步双重判断（接真实 LLM 的主路径）。"""
        rule = self._rule.classify(record)
        if not self._needs_llm(rule):
            return rule
        self.llm_calls += 1
        llm = await self._llm_cls.aclassify(record)
        if llm.is_known and llm.confidence >= self._llm_cls._threshold:
            return llm
        return rule


# ---- Config 读取 --------------------------------------------------------------

def _rule_conf_threshold() -> float:
    """规则直回阈值（Config 可配）。"""
    try:
        return float(getattr(get_config(), "rule_conf_threshold", None) or _DEFAULT_RULE_CONF_THRESHOLD)
    except (TypeError, ValueError):
        return _DEFAULT_RULE_CONF_THRESHOLD


def _llm_conf_threshold() -> float:
    """LLM 结果可信阈值（Config 可配）。"""
    try:
        return float(getattr(get_config(), "llm_conf_threshold", None) or _DEFAULT_LLM_CONF_THRESHOLD)
    except (TypeError, ValueError):
        return _DEFAULT_LLM_CONF_THRESHOLD


__all__ = [
    "DualLogClassifier",
    "LLMLogClassifier",
    "_DEFAULT_LLM_CONF_THRESHOLD",
    "_DEFAULT_RULE_CONF_THRESHOLD",
]
