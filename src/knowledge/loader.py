"""知识库加载与模糊匹配。

从 JSON 文件加载结构化知识库，支持 rapidfuzz 中文模糊匹配检索。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from src.config import get_config
from src.knowledge.schema import (
    ErrorCode,
    FAQEntry,
    KnowledgeBase,
    QOSEntry,
    SlurmCommand,
)

# 关键词精确命中时的模糊分加权（封顶 100）
_KEYWORD_HIT_BONUS: float = 25.0


class KnowledgeLoader:
    """知识库加载器。

    从 config 指定的 JSON 文件加载 FAQ、Slurm 命令、QOS 表和错误码映射。
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._kb: KnowledgeBase | None = None

    @property
    def kb(self) -> KnowledgeBase:
        if self._kb is None:
            raise RuntimeError("知识库尚未加载，请先调用 load()")
        return self._kb

    def load(self) -> KnowledgeBase:
        """加载全部知识库 JSON 文件。"""
        start = time.perf_counter()
        self._kb = KnowledgeBase(
            faq=self._load_faq(),
            commands=self._load_commands(),
            qos=self._load_qos(),
            error_codes=self._load_error_codes(),
        )
        elapsed = time.perf_counter() - start
        if elapsed > 0.5:
            import sys
            print(
                f"[KnowledgeLoader] 加载 {self._kb.faq_count} 条 FAQ "
                f"耗时 {elapsed:.3f}s (超过 0.5s 目标)",
                file=sys.stderr,
            )
        return self._kb

    def _resolve(self, filename: str) -> Path:
        return self._config.resolve_path(
            str(Path(self._config.data_dir) / filename)
        )

    def _load_json(self, path: Path) -> Any:
        if not path.exists():
            raise FileNotFoundError(f"知识库文件不存在: {path}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _load_faq(self) -> list[FAQEntry]:
        data = self._load_json(self._resolve(self._config.knowledge_faq_path))
        return [
            FAQEntry(
                id=item["id"],
                category=item.get("category", ""),
                title=item.get("title", ""),
                keywords=item.get("keywords", []),
                intents=item.get("intents", []),
                question=item.get("question", ""),
                answer=item.get("answer", ""),
                related_errors=item.get("related_errors", []),
                references=item.get("references", []),
            )
            for item in data.get("faq", [])
        ]

    def _load_commands(self) -> list[SlurmCommand]:
        data = self._load_json(
            self._resolve(self._config.knowledge_commands_path)
        )
        return [
            SlurmCommand(
                id=item["id"],
                command=item.get("command", ""),
                description=item.get("description", ""),
                example=item.get("example", ""),
                category=item.get("category", ""),
            )
            for item in data.get("slurm_commands", [])
        ]

    def _load_qos(self) -> list[QOSEntry]:
        data = self._load_json(self._resolve(self._config.knowledge_qos_path))
        return [
            QOSEntry(
                name=item["name"],
                display=item.get("display", ""),
                cpu=item.get("cpu", 0),
                gpu=item.get("gpu", 0),
                memory=item.get("memory", ""),
                max_walltime=item.get("max_walltime", ""),
                max_walltime_hours=item.get("max_walltime_hours", 0),
                description=item.get("description", ""),
            )
            for item in data.get("qos", [])
        ]

    def _load_error_codes(self) -> list[ErrorCode]:
        data = self._load_json(
            self._resolve(self._config.knowledge_error_codes_path)
        )
        return [
            ErrorCode(
                code=item["code"],
                type=item.get("type", ""),
                description=item.get("description", ""),
                category=item.get("category", ""),
            )
            for item in data.get("error_codes", [])
        ]


class KnowledgeMatcher:
    """知识库模糊匹配检索。

    基于 rapidfuzz 对 FAQ 条目的 search_text 做模糊匹配，
    返回匹配得分和排序结果。
    """

    def __init__(self, kb: KnowledgeBase) -> None:
        self._kb = kb
        self._config = get_config()
        self._choices = [entry.search_text for entry in kb.faq]

    def match(self, query: str, top_k: int | None = None) -> list[tuple[FAQEntry, float]]:
        """模糊匹配查询，返回排序后的 (条目, 得分) 列表。

        得分范围为 0-100，基础分由 rapidfuzz 的 partial_ratio 计算，
        若条目任一关键词在查询中精确命中（双向子串，长度≥2），
        基础分 ≥ 阈值时加 _KEYWORD_HIT_BONUS（封顶 100）。
        这修复了泛化提问（如"如何提交作业"）下纯模糊分并列导致
        答非所问条目排前的排序问题：关键词命中的对口条目得以胜出。
        """
        if not query.strip():
            return []
        if top_k is None:
            top_k = self._config.top_k_retrieve

        threshold = self._config.fuzzy_match_threshold

        # 候选池放大：关键词加权可能把纯模糊排名靠后的条目提到前面，
        # 若只取 limit=top_k 的窗口，这些条目连加权的机会都没有
        pool = max(top_k * 5, 20)
        raw: list[tuple[str, float, int]] = process.extract(
            query, self._choices, scorer=fuzz.partial_ratio, limit=pool
        )

        results: list[tuple[FAQEntry, float]] = []
        for _, score, idx in raw:
            if score < threshold:
                continue
            entry = self._kb.faq[idx]
            if self._keyword_hit(query, entry):
                score = min(100.0, score + _KEYWORD_HIT_BONUS)
            results.append((entry, score))

        # 按加权分降序（稳定排序，同分保持原始顺序），再截取 top_k
        results.sort(key=lambda pair: pair[1], reverse=True)
        return results[:top_k]

    @staticmethod
    def _keyword_hit(query: str, entry: FAQEntry) -> bool:
        """条目是否有任一关键词与查询精确互含（忽略大小写）。

        双向子串：关键词出现在查询中（如"提交作业" ⊂ "如何提交作业"），
        或查询包含在关键词中（如查询"sbatch" ⊂ 关键词"Invalid sbatch"）。
        长度 <2 的关键词不参与，避免单字符误命中。
        """
        q = query.lower()
        for kw in entry.keywords:
            k = kw.lower().strip()
            if len(k) < 2:
                continue
            if k in q or q in k:
                return True
        return False

    def match_one(self, query: str) -> tuple[FAQEntry | None, float]:
        """返回最佳匹配条目。"""
        matches = self.match(query, top_k=1)
        if matches:
            return matches[0]
        return None, 0.0

    def match_by_keyword(self, keyword: str) -> list[FAQEntry]:
        """按关键词精确匹配（用于错误码反向查找）。"""
        results: list[FAQEntry] = []
        kw_lower = keyword.lower()
        for entry in self._kb.faq:
            if any(kw_lower in k.lower() for k in entry.keywords):
                results.append(entry)
        return results


def load_knowledge_base() -> tuple[KnowledgeBase, KnowledgeMatcher]:
    """便捷函数：一键加载知识库并创建匹配器。"""
    loader = KnowledgeLoader()
    kb = loader.load()
    matcher = KnowledgeMatcher(kb)
    return kb, matcher
