"""/api/script 脚本改写对话端点（第 5 周周四集成）.

- POST   /api/script/parse                       sbatch 脚本解析（无状态）
- GET    /api/script/templates                   模板清单（无状态）
- POST   /api/script/generate                    模板生成脚本（无状态）
- POST   /api/script/suggest                     字段补齐建议（无状态）
- POST   /api/script/rewrite/start               开始改写（创建会话）
- GET    /api/script/rewrite/{sid}/status        会话状态（含双容器一致性）
- POST   /api/script/rewrite/{sid}/identify      识别变更
- POST   /api/script/rewrite/{sid}/collect       收集参数
- POST   /api/script/rewrite/{sid}/confirm       确认（返回修改稿+差分）
- POST   /api/script/rewrite/{sid}/apply         应用
- POST   /api/script/rewrite/{sid}/rollback      回退一步
- POST   /api/script/rewrite/{sid}/finish        完成
- GET    /api/script/rewrite/{sid}/diff          查看差分
- GET    /api/script/rewrite/{sid}/export        一键导出（文件下载）
- DELETE /api/script/rewrite/{sid}               删除会话

架构纪律：本路由只经 ``ScriptRewriteService`` 编排层调用，
禁止直接 import rewrite_flow/state_machine（双写一致性与 TTL
同步由 service 独家保证）。数据源口径：内存态会话（memory），
进程重启即失、单 worker 部署（v3.0 文档注明）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from src.script.service import ScriptRewriteService

router = APIRouter(prefix="/api/script", tags=["script"])


# ---- 请求模型 ----------------------------------------------------------------


class ParseRequest(BaseModel):
    """parse 请求体。"""

    script: str


class GenerateRequest(BaseModel):
    """generate 请求体。"""

    template_name: str
    overrides: dict[str, str] | None = None


class SuggestRequest(BaseModel):
    """suggest 请求体。"""

    fields: dict[str, str] = {}


class StartRequest(BaseModel):
    """rewrite/start 请求体。"""

    session_id: str
    script: str


class IdentifyRequest(BaseModel):
    """identify 请求体。"""

    changes: dict[str, Any] = {}


class CollectRequest(BaseModel):
    """collect 请求体。"""

    field: str
    value: Any


# ---- 共享单例（惰性，同 routes_flow 模式） --------------------------------------

_service: ScriptRewriteService | None = None


def get_script_service() -> ScriptRewriteService:
    """脚本改写编排器单例（测试可整体替换）。"""
    global _service
    if _service is None:
        _service = ScriptRewriteService()
    return _service


def _require(result: dict[str, Any] | None, session_id: str) -> dict[str, Any]:
    """service 返回 None 统一表现为会话不存在/已过期。"""
    if result is None:
        raise HTTPException(status_code=404, detail=f"会话不存在或已过期: {session_id}")
    return result


# ---- 无状态工具端点 ------------------------------------------------------------


@router.post("/parse")
async def parse_script(req: ParseRequest) -> dict[str, Any]:
    """解析 sbatch 脚本字段（短键保留原样，不映射）。"""
    return {"fields": get_script_service().parse(req.script), "data_source": "memory"}


@router.get("/templates")
async def list_templates() -> dict[str, Any]:
    """模板清单（名称 → 描述）。"""
    return {"templates": get_script_service().list_templates(), "data_source": "memory"}


@router.post("/generate")
async def generate_script(req: GenerateRequest) -> dict[str, Any]:
    """按模板生成脚本；未知模板返回 422。"""
    try:
        script = get_script_service().generate(req.template_name, req.overrides)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"script": script, "data_source": "memory"}


@router.post("/suggest")
async def suggest_fields(req: SuggestRequest) -> dict[str, Any]:
    """字段补齐建议 + 可读说明。"""
    service = get_script_service()
    return {
        "suggestions": service.suggest(req.fields),
        "explanation": service.explain_suggestions(req.fields),
        "data_source": "memory",
    }


# ---- 改写流程端点 --------------------------------------------------------------


@router.post("/rewrite/start")
async def rewrite_start(req: StartRequest) -> dict[str, Any]:
    """开始改写：创建会话并进入 IDENTIFY。"""
    session_id = req.session_id.strip()
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id 不能为空")
    return get_script_service().start(session_id, req.script)


@router.get("/rewrite/{session_id}/status")
async def rewrite_status(session_id: str) -> dict[str, Any]:
    """会话状态快照（含双容器一致性标记）。"""
    return _require(get_script_service().status(session_id), session_id)


@router.post("/rewrite/{session_id}/identify")
async def rewrite_identify(session_id: str, req: IdentifyRequest) -> dict[str, Any]:
    """识别要修改的字段。"""
    return _require(get_script_service().identify(session_id, req.changes), session_id)


@router.post("/rewrite/{session_id}/collect")
async def rewrite_collect(session_id: str, req: CollectRequest) -> dict[str, Any]:
    """收集单个参数。"""
    return _require(get_script_service().collect(session_id, req.field, req.value), session_id)


@router.post("/rewrite/{session_id}/confirm")
async def rewrite_confirm(session_id: str) -> dict[str, Any]:
    """确认修改：返回修改稿、差分文本与摘要。"""
    return _require(get_script_service().confirm(session_id), session_id)


@router.post("/rewrite/{session_id}/apply")
async def rewrite_apply(session_id: str) -> dict[str, Any]:
    """应用修改。"""
    return _require(get_script_service().apply(session_id), session_id)


@router.post("/rewrite/{session_id}/rollback")
async def rewrite_rollback(session_id: str) -> dict[str, Any]:
    """回退一步（栈空时 no-op）。"""
    return _require(get_script_service().rollback(session_id), session_id)


@router.post("/rewrite/{session_id}/finish")
async def rewrite_finish(session_id: str) -> dict[str, Any]:
    """完成改写。"""
    return _require(get_script_service().finish(session_id), session_id)


@router.get("/rewrite/{session_id}/diff")
async def rewrite_diff(session_id: str) -> dict[str, Any]:
    """查看当前差分。"""
    return _require(get_script_service().diff(session_id), session_id)


@router.get("/rewrite/{session_id}/export")
async def rewrite_export(session_id: str, filename: str | None = None) -> Response:
    """一键导出：文件下载（文件名取自作业名或显式指定）。"""
    exported = get_script_service().export(session_id, filename)
    if exported is None:
        raise HTTPException(status_code=404, detail=f"会话不存在或已过期: {session_id}")
    return Response(
        content=exported["content"],
        media_type=exported["media_type"],
        headers={"Content-Disposition": f'attachment; filename="{exported["filename"]}"'},
    )


@router.delete("/rewrite/{session_id}", status_code=204)
async def rewrite_delete(session_id: str) -> Response:
    """删除会话（双容器同步清理）。"""
    get_script_service().delete(session_id)
    return Response(status_code=204)
