"""脚本改写对话流程（第 5 周，A 职责）。

状态驱动的 sbatch 脚本多轮改写管线：
``start_rewrite → identify_changes → collect_params（可多步） →
confirm_changes → apply_changes → finish_rewrite``。

契约来源：docs/week5-A-state-machine-design.md §六
（test_script_rewrite_flow.py，12 用例）。要点：
- confirm_changes 应用替换后状态置 **CONFIRM**（而非 APPLY，APPLY 由
  apply_changes 显式触发）；
- step_history 只增不减（回退不裁剪步骤历史）；
- 替换仅覆盖 4 字段映射（partition/-p、time/-t、mem/--mem、gres/--gres），
  其他字段静默跳过；非 #SBATCH 行不受影响；
- ``.contexts`` 容器属性供外部直接索引（验收测试的访问方式）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# 改写支持字段 → sbatch 指令映射（其余字段静默跳过）
_FIELD_PARAM_MAP: dict[str, str] = {
    "partition": "-p",
    "time": "-t",
    "mem": "--mem",
    "gres": "--gres",
}


class RewriteState(Enum):
    """改写流程状态（6 态）."""

    INIT = "init"
    IDENTIFY = "identify"
    COLLECT = "collect"
    CONFIRM = "confirm"
    APPLY = "apply"
    DONE = "done"


@dataclass
class RewriteContext:
    """改写上下文：原始/修改后脚本、变更集与步骤历史."""

    session_id: str
    state: RewriteState = RewriteState.INIT
    original_script: str = ""
    modified_script: str = ""
    changes: dict[str, Any] = field(default_factory=dict)
    step_history: list[dict[str, Any]] = field(default_factory=list)

    def save_step(self, step_name: str, data: Any) -> None:
        """记录一步流程历史（只增不减）."""
        self.step_history.append({"step": step_name, "data": data, "state": self.state})


class ScriptRewriteFlow:
    """对话式脚本改写流程管理器."""

    def __init__(self) -> None:
        self.contexts: dict[str, RewriteContext] = {}

    def start_rewrite(self, session_id: str, script: str) -> RewriteContext:
        """开始改写：保存原始脚本并进入 IDENTIFY 状态."""
        context = RewriteContext(session_id=session_id, original_script=script)
        context.state = RewriteState.IDENTIFY
        self.contexts[session_id] = context
        return context

    def identify_changes(self, session_id: str, changes: dict[str, Any]) -> bool:
        """识别要修改的字段（整体替换变更集），进入 COLLECT 状态."""
        context = self.contexts.get(session_id)
        if context is None:
            return False
        context.changes = changes
        context.state = RewriteState.COLLECT
        context.save_step("identify", changes)
        return True

    def collect_params(self, session_id: str, field_name: str, value: Any) -> bool:
        """收集一个参数值（可多次调用，逐步收集）."""
        context = self.contexts.get(session_id)
        if context is None:
            return False
        context.changes[field_name] = value
        context.save_step("collect", {"field": field_name, "value": value})
        return True

    def confirm_changes(self, session_id: str) -> str | None:
        """确认修改：应用参数替换，返回修改后脚本。

        替换后状态置 CONFIRM（展示待应用），失败（会话不存在）返回 None。
        """
        context = self.contexts.get(session_id)
        if context is None:
            return None

        modified = context.original_script
        for field_name, value in context.changes.items():
            param = _FIELD_PARAM_MAP.get(field_name)
            if param is not None:
                modified = self._replace_param(modified, param, str(value))

        context.modified_script = modified
        context.state = RewriteState.CONFIRM
        context.save_step("confirm", None)
        return modified

    def apply_changes(self, session_id: str) -> bool:
        """应用修改（CONFIRM → APPLY）."""
        context = self.contexts.get(session_id)
        if context is None:
            return False
        context.state = RewriteState.APPLY
        context.save_step("apply", None)
        return True

    def finish_rewrite(self, session_id: str) -> bool:
        """完成改写（→ DONE）."""
        context = self.contexts.get(session_id)
        if context is None:
            return False
        context.state = RewriteState.DONE
        context.save_step("finish", None)
        return True

    @staticmethod
    def _replace_param(script: str, param: str, value: str) -> str:
        """替换脚本中的单个指令参数，兼容两种指令格式。

        优先 ``--key=value`` 等号格式；否则 ``--key value`` / ``-k value``
        空格格式。非 #SBATCH 行不含指令前缀，不受影响。
        """
        # --key=value 格式
        pattern_eq = rf"{re.escape(param)}=\S+"
        if re.search(pattern_eq, script):
            return re.sub(pattern_eq, f"{param}={value}", script)

        # --key value 或 -k value 格式
        pattern_space = rf"{re.escape(param)}\s+\S+"
        return re.sub(pattern_space, f"{param} {value}", script)


__all__ = ["RewriteContext", "RewriteState", "ScriptRewriteFlow"]
