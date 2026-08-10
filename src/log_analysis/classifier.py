"""错误分类器: 4 大类 + 10 子类。

根据作业记录 (JobRecord) 的多个信号判定错误类别:
- scontrol 的 Reason 字段 (最可靠, 常为 Slurm 明确错误码)
- ExitCode (如 137 = 被 OOM 杀死, 126/127 = 脚本/命令问题)
- JobName (约定命名, 如 train_oom 含 oom 线索)

设计要点(鲁棒性):
- 多信号加权: 任一信号命中即累积得分, 选出置信度最高的子类。
- 冲突容错: 信号方向冲突时按得分取最优; 全部无法归类时返回 unknown,
  不抛异常、不硬猜。
- 脏数据容错: 空 reason / 非数字 exit_code / None 字段均安全处理。
- 大小写归一: Reason 常为大写, 统一小写后匹配。
- 对接友好: 输出 ErrorClassification 结构化结果, 供修复生成器 fix_generator
  与后续 /api/jobs/{job_id}/diagnose 端点直接消费。

典型用法::

    from src.log_analysis.classifier import ErrorClassifier
    cls = ErrorClassifier()
    result = cls.classify(record)   # -> ErrorClassification
    print(result.category, result.subtype, result.confidence)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.knowledge.loader import KnowledgeLoader
from src.log_analysis.commands import JobRecord

# ---- 枚举常量(字符串, 便于序列化给 API) ------------------------------------

CAT_OOM = "oom"
CAT_SCRIPT = "script"
CAT_ENV = "env"
CAT_PERMISSION = "permission"

SUBTYPE_LABELS: dict[str, str] = {
    # OOM
    "gpu_oom": "GPU 显存不足 (OOM)",
    "mem_oom": "系统内存不足 (OOM)",
    "disk_full": "磁盘空间不足",
    # 脚本错误
    "syntax_error": "脚本语法错误",
    "path_error": "路径或文件不存在",
    "dependency_error": "依赖缺失或导入失败",
    # 环境缺失
    "conda_missing": "conda 环境未激活",
    "module_missing": "Python 模块未安装",
    "cuda_mismatch": "CUDA / 驱动版本不匹配",
    "kernel_issue": "内核 / 指令集兼容问题",
    # 权限限制
    "qos_limit": "QOS / 资源配额超限",
    "permission_denied": "文件 / 目录权限不足",
}

# 子类 -> 所属大类
SUBTYPE_CATEGORY: dict[str, str] = {
    "gpu_oom": CAT_OOM,
    "mem_oom": CAT_OOM,
    "disk_full": CAT_OOM,
    "syntax_error": CAT_SCRIPT,
    "path_error": CAT_SCRIPT,
    "dependency_error": CAT_SCRIPT,
    "conda_missing": CAT_ENV,
    "module_missing": CAT_ENV,
    "cuda_mismatch": CAT_ENV,
    "kernel_issue": CAT_ENV,
    "qos_limit": CAT_PERMISSION,
    "permission_denied": CAT_PERMISSION,
}


# ---- 结构化结果 --------------------------------------------------------------

@dataclass
class ErrorClassification:
    """一次错误分类的结果。"""

    record: JobRecord
    category: str = "unknown"
    subtype: str = "unknown"
    confidence: float = 0.0  # 0-1
    signals_hit: list[str] = field(default_factory=list)  # 命中的信号描述

    @property
    def label(self) -> str:
        """人类可读的类别描述。"""
        if self.subtype in SUBTYPE_LABELS:
            return SUBTYPE_LABELS[self.subtype]
        return f"未知错误类别 ({self.category})"

    @property
    def is_known(self) -> bool:
        return self.subtype != "unknown"


# ---- 信号定义 -----------------------------------------------------------------

@dataclass(frozen=True)
class Signal:
    """单个判定信号: 匹配方式 + 关键词 + 指向的子类 + 权重。"""

    subtype: str
    weight: float
    # 在哪个字段匹配
    reason_kw: str | None = None
    exit_code: int | None = None
    name_kw: str | None = None

    def matches(self, reason: str, exit_code: int | None, name: str) -> bool:
        """判断该信号是否命中。"""
        return (
            (self.reason_kw is not None and self.reason_kw in reason)
            or (self.exit_code is not None and exit_code == self.exit_code)
            or (self.name_kw is not None and self.name_kw in name)
        )

    def describe(self) -> str:
        if self.reason_kw is not None:
            return f"Reason包含[{self.reason_kw}]"
        if self.exit_code is not None:
            return f"ExitCode={self.exit_code}"
        return f"JobName包含[{self.name_kw}]"


# 判定信号表
_SIGNALS: tuple[Signal, ...] = (
    # ---- OOM ----
    Signal("gpu_oom", 1.0, reason_kw="cuda out of memory"),
    Signal("gpu_oom", 0.7, name_kw="oom"),
    Signal("mem_oom", 1.0, reason_kw="oom-killer"),
    Signal("mem_oom", 0.8, reason_kw="out of memory"),
    Signal("mem_oom", 0.6, exit_code=137),
    Signal("disk_full", 1.0, reason_kw="no space left on device"),
    Signal("disk_full", 0.8, reason_kw="disk quota"),
    # ---- 脚本错误 ----
    Signal("syntax_error", 1.0, reason_kw="syntaxerror"),
    Signal("syntax_error", 0.7, reason_kw="parseerror"),
    Signal("path_error", 1.0, reason_kw="no such file"),
    Signal("path_error", 0.7, reason_kw="not found"),
    Signal("dependency_error", 1.0, reason_kw="modulenotfounderror"),
    Signal("dependency_error", 1.0, reason_kw="importerror"),
    # ---- 环境缺失 ----
    Signal("conda_missing", 1.0, reason_kw="conda: command not found"),
    Signal("conda_missing", 0.8, reason_kw="conda"),
    Signal("module_missing", 1.0, reason_kw="modulenotfounderror"),
    Signal("module_missing", 0.7, reason_kw="no module named"),
    Signal("cuda_mismatch", 1.0, reason_kw="library version mismatch"),
    Signal("cuda_mismatch", 0.7, reason_kw="driver/library"),
    Signal("kernel_issue", 1.0, reason_kw="illegal instruction"),
    Signal("kernel_issue", 0.8, reason_kw="glibcxx"),
    # ---- 权限限制 ----
    Signal("qos_limit", 1.0, reason_kw="qosmaxwall"),
    Signal("qos_limit", 1.0, reason_kw="qosmaxcpu"),
    Signal("qos_limit", 1.0, reason_kw="qos"),
    Signal("qos_limit", 0.6, reason_kw="due to time limit"),
    Signal("permission_denied", 1.0, reason_kw="permission denied"),
    Signal("permission_denied", 0.7, reason_kw="denied"),
)

# 非 0 退出码的默认兜底(无更明确信号时的弱提示)
_DEFAULT_SUBTYPE_BY_EXIT: dict[int, tuple[str, float]] = {
    137: ("mem_oom", 0.5),
    1: ("dependency_error", 0.3),
    2: ("syntax_error", 0.3),
    126: ("permission_denied", 0.4),
    127: ("path_error", 0.4),
}


class ErrorClassifier:
    """基于多信号规则表的错误分类器。"""

    def __init__(self) -> None:
        # 加载知识库错误码表, 用于 Reason 的补充匹配
        self._kb_codes: set[str] = set()
        self._load_error_codes()

    def _load_error_codes(self) -> None:
        """加载知识库错误码原文（小写）, 用于 Reason 的补充匹配。"""
        try:
            loader = KnowledgeLoader()
            kb = loader.load()
            self._kb_codes = {
                code_entry.code.lower() for code_entry in kb.error_codes
            }
        except Exception:
            self._kb_codes = set()

    def classify(self, record: JobRecord) -> ErrorClassification:
        """对作业记录分类, 返回类别 + 置信度。"""
        reason_raw = record.reason or ""
        name = record.job_name or ""
        exit_code = self._parse_exit_code(record.exit_code)

        # 归一化大小写(Reason 常为大写)
        reason = reason_raw.lower()
        name_lower = name.lower()

        # 累积每个子类的得分
        scores: dict[str, float] = {}
        signals_hit: list[str] = []
        for sig in _SIGNALS:
            if sig.matches(reason, exit_code, name_lower):
                scores[sig.subtype] = scores.get(sig.subtype, 0.0) + sig.weight
                signals_hit.append(sig.describe())

        # 知识库错误码补充: Reason 精确命中 error_codes 表则大幅加权
        for code in self._kb_codes:
            if code and code in reason:
                mapped = self._map_error_code_to_subtype(code)
                if mapped:
                    scores[mapped] = scores.get(mapped, 0.0) + 1.0
                    signals_hit.append(f"错误码[{code}]")

        if not scores:
            # 用退出码兜底
            fallback = _DEFAULT_SUBTYPE_BY_EXIT.get(exit_code) if exit_code is not None else None
            if fallback is not None:
                subtype, conf = fallback
                return ErrorClassification(
                    record=record,
                    category=SUBTYPE_CATEGORY[subtype],
                    subtype=subtype,
                    confidence=conf,
                    signals_hit=[f"ExitCode={exit_code} (兜底)"],
                )
            return ErrorClassification(record=record, confidence=0.0)

        # 归一化置信度: 得分越高越确定
        top_subtype, top_score = max(scores.items(), key=lambda kv: kv[1])
        total = sum(scores.values())
        confidence = min(1.0, top_score / max(total, 1e-9) + 0.3 * min(top_score, 1.0))

        return ErrorClassification(
            record=record,
            category=SUBTYPE_CATEGORY[top_subtype],
            subtype=top_subtype,
            confidence=confidence,
            signals_hit=signals_hit,
        )

    @staticmethod
    def _parse_exit_code(exit_code: str | None) -> int | None:
        """解析 ExitCode (形如 '137:0' / '137' / '0:0'), 非法返回 None。"""
        if not exit_code:
            return None
        main = exit_code.split(":", 1)[0].strip()
        try:
            return int(main)
        except ValueError:
            return None

    @staticmethod
    def _map_error_code_to_subtype(code: str) -> str | None:
        """把知识库错误码原文映射到子类。"""
        low = code.lower()
        if "cuda" in low or "oom" in low:
            return "gpu_oom"
        if "oom" in low:
            return "mem_oom"
        if "space" in low or "disk" in low or "quota" in low:
            return "disk_full"
        if "illegal instruction" in low or "glibcxx" in low:
            return "kernel_issue"
        if "qos" in low or "time limit" in low:
            return "qos_limit"
        if "conda" in low:
            return "conda_missing"
        if "modulenotfound" in low or "module" in low:
            return "module_missing"
        if "driver" in low or "library" in low or "mismatch" in low:
            return "cuda_mismatch"
        if "no such file" in low or "not found" in low:
            return "path_error"
        if "syntax" in low or "parse" in low:
            return "syntax_error"
        if "permission" in low or "denied" in low:
            return "permission_denied"
        return None


__all__ = [
    "CAT_ENV",
    "CAT_OOM",
    "CAT_PERMISSION",
    "CAT_SCRIPT",
    "SUBTYPE_CATEGORY",
    "SUBTYPE_LABELS",
    "ErrorClassification",
    "ErrorClassifier",
]
