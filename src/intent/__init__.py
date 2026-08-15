"""意图识别模块：关键词匹配 + LLM 兜底双通道分类。

对外暴露 intent 引擎的意图常量与核心类（re-export 自 engine.py），
供 pipeline 与上层直接 `from src.intent import ...` 使用。
"""

from src.intent.engine import (
    INTENT_ERROR_DIAGNOSIS,
    INTENT_JOB_STATUS,
    INTENT_JOB_SUBMISSION,
    INTENT_PERMISSION,
    IntentEngine,
    IntentResult,
)

__all__ = [
    "IntentEngine",
    "IntentResult",
    "INTENT_ERROR_DIAGNOSIS",
    "INTENT_JOB_STATUS",
    "INTENT_JOB_SUBMISSION",
    "INTENT_PERMISSION",
]
