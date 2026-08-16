"""脚本改写集成编排层（第 5 周，A 职责）。

桥接 ``DialogManager``（对话状态机）与 ``ScriptRewriteFlow``（脚本数据）
的 Facade，单一 session_id 同时作两容器键。

集成决策（docs/week5-A-state-machine-design.md 附录：双容器桥接方案）：

- **生命周期**：只归 DialogManager 的 TTL 裁决。入口先 ``get_session()``，
  过期/不存在即同步 ``flow.discard()`` 清数据，对上层表现为会话失效；
- **状态同步**：flow 走一步、状态机同步转一步（先写字段快照再转状态，
  保证 update_state 快照含最新字段）；状态机对外是"当前状态"唯一真相；
- **回退**：状态机走快照栈；数据层按快照恢复的字段重置 changes，
  original_script 全程不可变，回退天然廉价。

纪律约束：routes 一律经本层调用，禁止直接 import rewrite_flow
（否则双写一致性与 TTL 同步失效）。
"""

from __future__ import annotations

from typing import Any

from src.dialog.state_machine import DialogManager, DialogState
from src.script.differ import ScriptDiffer
from src.script.exporter import ScriptExporter
from src.script.field_suggester import FieldSuggester
from src.script.generator import ScriptGenerator
from src.script.parser import SbatchParser
from src.script.rewrite_flow import RewriteState, ScriptRewriteFlow
from src.script.templates import TEMPLATES

# RewriteState → DialogState（同名态一一对应；ROLLBACK 为栈操作语义，无 flow 对应）
_STATE_MAP: dict[RewriteState, DialogState] = {
    RewriteState.INIT: DialogState.INIT,
    RewriteState.IDENTIFY: DialogState.IDENTIFY,
    RewriteState.COLLECT: DialogState.COLLECT,
    RewriteState.CONFIRM: DialogState.CONFIRM,
    RewriteState.APPLY: DialogState.APPLY,
    RewriteState.DONE: DialogState.DONE,
}
_REVERSE_STATE_MAP: dict[DialogState, RewriteState] = {v: k for k, v in _STATE_MAP.items()}


class ScriptRewriteService:
    """脚本改写编排器：状态机 + 改写流程 + 工具层的唯一入口。"""

    def __init__(
        self,
        manager: DialogManager | None = None,
        flow: ScriptRewriteFlow | None = None,
        ttl: int = 3600,
    ) -> None:
        self._manager = manager or DialogManager(ttl=ttl)
        self._flow = flow or ScriptRewriteFlow()
        self._parser = SbatchParser()
        self._generator = ScriptGenerator()
        self._differ = ScriptDiffer()
        self._suggester = FieldSuggester()
        self._exporter = ScriptExporter()

    # ---- 无状态工具 ----------------------------------------------------------

    def parse(self, script: str) -> dict[str, str]:
        """解析 sbatch 脚本字段。"""
        return self._parser.parse(script)

    def generate(self, template_name: str, overrides: dict[str, str] | None = None) -> str:
        """按模板生成脚本。"""
        return self._generator.generate(template_name, overrides)

    def list_templates(self) -> dict[str, str]:
        """模板清单（名称 → 描述）。"""
        return {name: tpl.description for name, tpl in TEMPLATES.items()}

    def suggest(self, fields: dict[str, str]) -> dict[str, str]:
        """字段补齐建议。"""
        return self._suggester.suggest(fields)

    def explain_suggestions(self, fields: dict[str, str]) -> list[str]:
        """字段建议的可读说明。"""
        return self._suggester.explain(fields)

    # ---- 生命周期 ------------------------------------------------------------

    def _alive(self, session_id: str) -> bool:
        """TTL 裁决：状态机会话失效则同步清 flow 数据。"""
        if self._manager.get_session(session_id) is None:
            self._flow.discard(session_id)
            return False
        return True

    def _sync(self, session_id: str) -> None:
        """把状态机同步到 flow 当前状态（先写字段，再转状态）。"""
        flow_ctx = self._flow.contexts[session_id]
        manager_ctx = self._manager.get_session(session_id)
        manager_ctx.collected_fields = dict(flow_ctx.changes)
        target = _STATE_MAP[flow_ctx.state]
        if manager_ctx.state != target:
            self._manager.update_state(session_id, target)

    # ---- 改写流程 ------------------------------------------------------------

    def start(self, session_id: str, script: str) -> dict[str, Any]:
        """开始改写：创建双容器会话并进入 IDENTIFY。"""
        self._manager.create_session(session_id)
        self._flow.start_rewrite(session_id, script)
        self._sync(session_id)
        return self.status(session_id)  # type: ignore[return-value]

    def identify(self, session_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        """识别要修改的字段（整体替换变更集）。"""
        if not self._alive(session_id):
            return None
        if not self._flow.identify_changes(session_id, changes):
            return None
        self._sync(session_id)
        return self.status(session_id)

    def collect(self, session_id: str, field_name: str, value: Any) -> dict[str, Any] | None:
        """收集单个参数值（可多次）。"""
        if not self._alive(session_id):
            return None
        if not self._flow.collect_params(session_id, field_name, value):
            return None
        self._sync(session_id)
        return self.status(session_id)

    def confirm(self, session_id: str) -> dict[str, Any] | None:
        """确认修改：应用替换，附带差分文本与摘要。"""
        if not self._alive(session_id):
            return None
        modified = self._flow.confirm_changes(session_id)
        if modified is None:
            return None
        self._sync(session_id)

        ctx = self._flow.contexts[session_id]
        summary = self._differ.summarize(ctx.original_script, modified)
        result = self.status(session_id)
        result.update(
            {
                "modified_script": modified,
                "diff_text": self._differ.diff(ctx.original_script, modified),
                "diff_summary": {
                    "removed": summary.removed,
                    "added": summary.added,
                    "replaced": [list(pair) for pair in summary.replaced],
                },
            }
        )
        return result

    def apply(self, session_id: str) -> dict[str, Any] | None:
        """应用修改（CONFIRM → APPLY）。"""
        if not self._alive(session_id):
            return None
        if not self._flow.apply_changes(session_id):
            return None
        self._sync(session_id)
        return self.status(session_id)

    def finish(self, session_id: str) -> dict[str, Any] | None:
        """完成改写（→ DONE）。"""
        if not self._alive(session_id):
            return None
        if not self._flow.finish_rewrite(session_id):
            return None
        self._sync(session_id)
        return self.status(session_id)

    def rollback(self, session_id: str) -> dict[str, Any] | None:
        """回退一步：状态机走快照栈，数据层按恢复的字段重置。"""
        if not self._alive(session_id):
            return None
        if self._manager.get_rollback_depth(session_id) == 0:
            return self.status(session_id)  # 无可回退：no-op

        self._manager.rollback(session_id)
        manager_ctx = self._manager.get_session(session_id)
        flow_ctx = self._flow.contexts.get(session_id)
        if flow_ctx is not None and manager_ctx is not None:
            flow_ctx.changes = dict(manager_ctx.collected_fields)
            flow_ctx.modified_script = ""
            flow_ctx.state = _REVERSE_STATE_MAP.get(manager_ctx.state, RewriteState.INIT)
        return self.status(session_id)

    # ---- 查询与导出 ----------------------------------------------------------

    def status(self, session_id: str) -> dict[str, Any] | None:
        """会话状态快照（含双容器一致性标记）。"""
        manager_ctx = self._manager.get_session(session_id)
        flow_ctx = self._flow.contexts.get(session_id)
        if manager_ctx is None or flow_ctx is None:
            return None
        return {
            "session_id": session_id,
            "dialog_state": manager_ctx.state.value,
            "flow_state": flow_ctx.state.value,
            "consistent": _STATE_MAP[flow_ctx.state] == manager_ctx.state,
            "changes": dict(flow_ctx.changes),
            "has_modified": bool(flow_ctx.modified_script),
            "step_count": len(flow_ctx.step_history),
            "rollback_depth": self._manager.get_rollback_depth(session_id),
        }

    def diff(self, session_id: str) -> dict[str, Any] | None:
        """查看当前差分（未确认时为空）。"""
        if not self._alive(session_id):
            return None
        ctx = self._flow.contexts.get(session_id)
        if ctx is None:
            return None
        modified = ctx.modified_script or ctx.original_script
        summary = self._differ.summarize(ctx.original_script, modified)
        return {
            "diff_text": self._differ.diff(ctx.original_script, modified),
            "changed": summary.changed,
        }

    def export(self, session_id: str, filename: str | None = None) -> dict[str, str] | None:
        """一键导出：优先修改后脚本，否则原稿；文件名取自作业名。"""
        if not self._alive(session_id):
            return None
        ctx = self._flow.contexts.get(session_id)
        if ctx is None:
            return None
        script = ctx.modified_script or ctx.original_script
        parsed = self._parser.parse(script)
        job_name = parsed.get("J") or parsed.get("job_name") or session_id
        return self._exporter.build_response(script, job_name=job_name, filename=filename)

    def delete(self, session_id: str) -> None:
        """显式删除会话（双容器同步清理）。"""
        self._manager.delete_session(session_id)
        self._flow.discard(session_id)


__all__ = ["ScriptRewriteService"]
