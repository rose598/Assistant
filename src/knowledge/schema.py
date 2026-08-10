"""知识库数据类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FAQEntry:
    """单条 FAQ 条目。"""

    id: str
    category: str
    title: str
    keywords: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    question: str = ""
    answer: str = ""
    related_errors: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)

    @property
    def search_text(self) -> str:
        """用于模糊匹配的全文搜索文本。"""
        parts = [self.title, self.question, " ".join(self.keywords)]
        return " ".join(parts)


@dataclass
class SlurmCommand:
    """Slurm 命令参考条目。"""

    id: str
    command: str
    description: str
    example: str = ""
    category: str = ""


@dataclass
class QOSEntry:
    """QOS 资源方案条目。"""

    name: str
    display: str
    cpu: int
    gpu: int
    memory: str
    max_walltime: str
    max_walltime_hours: int
    description: str


@dataclass
class ErrorCode:
    """错误码映射条目。"""

    code: str
    type: str
    description: str
    category: str


@dataclass
class KnowledgeBase:
    """知识库全集。"""

    faq: list[FAQEntry] = field(default_factory=list)
    commands: list[SlurmCommand] = field(default_factory=list)
    qos: list[QOSEntry] = field(default_factory=list)
    error_codes: list[ErrorCode] = field(default_factory=list)

    @property
    def faq_count(self) -> int:
        return len(self.faq)
