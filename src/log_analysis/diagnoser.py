"""作业失败原因诊断与解决方案映射。

根据日志命令层得到的作业记录(JobRecord),识别失败原因并映射到
知识库 FAQ 条目,返回可直接展示的解决方案。

鲁棒性设计：
- 仅对"确实失败"的作业做诊断(成功/运行/排队中跳过)。
- 优先级:精确错误码匹配(scontrol Reason 命中 error_codes 表)>
  关键词/模糊匹配 > 通用兜底建议。
- 通过 FAQ 的 related_errors / category 把错误码关联到具体 FAQ。
- 任何映射不到时返回通用指导,不抛异常。

典型用法::

    diagnoser = JobDiagnoser()
    diag = await diagnoser.diagnose(record)
    print(diag.solution)
"""

from __future__ import annotations

from dataclasses import dataclass

from src.knowledge.loader import KnowledgeLoader, KnowledgeMatcher
from src.knowledge.schema import ErrorCode, FAQEntry, KnowledgeBase
from src.log_analysis.commands import JobRecord


@dataclass
class Diagnosis:
    """一次失败的诊断结果。"""

    record: JobRecord
    matched_faq: FAQEntry | None = None
    matched_code: ErrorCode | None = None
    reason_text: str = ""  # 对失败原因的可读描述
    solution: str = ""  # 最终给出的解决方案/建议
    confidence: float = 0.0  # 0-1 匹配置信度
    is_failed: bool = False  # 是否确实为失败作业

    @property
    def found(self) -> bool:
        """是否命中了具体的 FAQ/错误码方案。"""
        return self.matched_faq is not None or self.matched_code is not None


class JobDiagnoser:
    """失败原因 -> 知识库解决方案 映射器。"""

    def __init__(
        self,
        kb: KnowledgeBase | None = None,
        matcher: KnowledgeMatcher | None = None,
    ) -> None:
        if kb is None or matcher is None:
            loader = KnowledgeLoader()
            kb = loader.load()
            matcher = KnowledgeMatcher(kb)
        self._kb = kb
        self._matcher = matcher

        # 预构建 错误码原始串(小写) -> ErrorCode 索引
        self._code_index: dict[str, ErrorCode] = {}
        for code_entry in kb.error_codes:
            raw = code_entry.code.lower()
            self._code_index[raw] = code_entry

        # 预构建 错误码 category -> FAQ 列表 (按 category 关联, 比 related_errors 更可靠)
        self._category_index: dict[str, list[FAQEntry]] = {}
        for faq in kb.faq:
            if faq.category:
                self._category_index.setdefault(faq.category, []).append(faq)

    # -- 主入口 --
    def diagnose(self, record: JobRecord) -> Diagnosis:
        """诊断单个作业记录。"""
        if not record.is_failed:
            return Diagnosis(record=record, is_failed=False)

        reason = (record.reason or "").strip()
        exit_code = record.exit_code or ""
        diag = Diagnosis(record=record, is_failed=True, reason_text=reason)

        # 1. 精确错误码匹配(最高优先)
        code_match = self._match_error_code(reason)
        if code_match is not None:
            code_entry, faqs = code_match
            diag.matched_code = code_entry
            diag.matched_faq = faqs[0] if faqs else None
            diag.confidence = 1.0
            diag.reason_text = code_entry.description or reason
            diag.solution = self._build_solution(diag)
            return diag

        # 2. 模糊匹配(用 reason + exitcode 组成查询串)
        query = f"{reason} {exit_code}".strip()
        if query:
            matches = self._matcher.match(query, top_k=3)
            if matches:
                faq, score = matches[0]
                diag.matched_faq = faq
                diag.confidence = max(0.0, min(1.0, score / 100.0))
                diag.solution = self._build_solution(diag)
                return diag

        # 3. 通用兜底
        diag.confidence = 0.0
        diag.solution = self._generic_solution(record)
        return diag

    # -- 内部 --
    def _match_error_code(
        self, reason: str
    ) -> tuple[ErrorCode, list[FAQEntry]] | None:
        """在错误码表中精确匹配 reason；返回 (ErrorCode, 关联FAQ列表)。"""
        if not reason:
            return None
        reason_lower = reason.lower()
        # 优先完整/部分匹配已知错误码
        matched: ErrorCode | None = None
        best_len = 0
        for raw, entry in self._code_index.items():
            if raw and raw in reason_lower and len(raw) > best_len:
                matched = entry
                best_len = len(raw)
        if matched is None:
            return None
        # 用错误码的 category 关联同分类的 FAQ (避免 related_errors 反查错位)
        faqs = self._category_index.get(matched.category, [])
        # 同分类有多个 FAQ 时, 优先选 keywords 命中该错误码的那条
        code_lower = matched.code.lower()
        for faq in faqs:
            if any(
                code_lower in kw.lower() or kw.lower() in code_lower
                for kw in faq.keywords
            ):
                return matched, [faq]
        return matched, faqs

    @staticmethod
    def _build_solution(diag: Diagnosis) -> str:
        """根据已命中的 FAQ/错误码拼接解决方案文本。"""
        parts: list[str] = []
        if diag.matched_faq is not None:
            parts.append(diag.matched_faq.answer)
        elif diag.matched_code is not None:
            parts.append(diag.matched_code.description or "检测到平台错误。")
        # 补充命令级排错提示(若答案未包含)
        record = diag.record
        hints: list[str] = []
        if record.job_id:
            hints.append(
                f"可用 `scontrol show job {record.job_id}` 与 "
                "`tail -n 80 <日志文件>.err` 进一步定位。"
            )
        if hints:
            parts.append("\n\n" + "\n".join(hints))
        return "\n".join(parts) if parts else diag.reason_text

    @staticmethod
    def _generic_solution(record: JobRecord) -> str:
        """失败但无法精确归因时的通用处理建议。"""
        lines = [
            "未能精确定位失败原因，建议按以下顺序排查：",
            "1. `squeue -u \"$USER\"` 确认作业状态。",
            "2. 读取作业的 .err 与 .out 日志尾部（`tail -n 80`）。",
            "3. 若任务申请了 GPU, 在日志中检查 `nvidia-smi` 输出。",
            "4. 记录完整错误信息和作业 ID, 便于进一步求助。",
        ]
        if record.job_id:
            lines.append(f"本次作业 ID: {record.job_id}")
        return "\n".join(lines)


__all__ = ["Diagnosis", "JobDiagnoser"]
