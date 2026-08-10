"""/api/feedback 用户反馈收集端点.

接收前端"有用/无用"反馈, 写入 SQLite (aiosqlite) 持久化, 供后续统计与改进.
存储路径对齐 D 框架 config 的 data 目录约定, 但独立于主业务库, 便于移植.

鲁棒性:
- 非法/缺失字段均被 pydantic 拦截
- 数据库初始化失败时优雅降级(返回 503, 不抛堆栈)
- 所有写入为异步, 不阻塞事件循环
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

# SQLite 落盘位置: 项目根 /data/feedback.db
_BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
_DB_PATH: Path = _BASE_DIR / "data" / "feedback.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    useful     INTEGER NOT NULL CHECK (useful IN (0, 1)),
    question   TEXT,
    answer     TEXT,
    source     TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


# ---- 请求模型 ----------------------------------------------------------------

class FeedbackRequest(BaseModel):
    """单条反馈: 有用(1)/无用(0) + 可选上下文."""

    useful: int = Field(..., ge=0, le=1, description="1=有用, 0=无用")
    question: str | None = Field(default=None, max_length=5000, description="原始问题")
    answer: str | None = Field(default=None, max_length=10000, description="助手回复")
    source: str | None = Field(default=None, max_length=200, description="来源/触发点")


# ---- 数据库初始化 ------------------------------------------------------------

async def _init_db() -> None:
    """确保 data 目录与 feedback 表存在."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(_SCHEMA)
        await db.commit()


# ---- 端点 --------------------------------------------------------------------

@router.post("")
async def submit_feedback(req: FeedbackRequest) -> dict[str, object]:
    """记录一条用户反馈."""
    try:
        await _init_db()
        async with aiosqlite.connect(_DB_PATH) as db:
            await db.execute(
                "INSERT INTO feedback (useful, question, answer, source) "
                "VALUES (?, ?, ?, ?)",
                (req.useful, req.question, req.answer, req.source),
            )
            await db.commit()
    except Exception:
        logger.exception("反馈写入失败")
        raise HTTPException(status_code=503, detail="反馈服务暂不可用") from None
    return {"status": "ok", "recorded": True}


@router.get("/stats")
async def feedback_stats() -> dict[str, int]:
    """反馈统计: 总数 / 好评数 / 好评率(用于看板)."""
    try:
        await _init_db()
        async with aiosqlite.connect(_DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM feedback") as cur:
                row = await cur.fetchone()
                total = int(row[0]) if row is not None else 0
            async with db.execute(
                "SELECT COUNT(*) FROM feedback WHERE useful = 1"
            ) as cur:
                row = await cur.fetchone()
                useful = int(row[0]) if row is not None else 0
    except Exception:
        logger.exception("反馈统计失败")
        raise HTTPException(status_code=503, detail="反馈服务暂不可用") from None
    rate = round(useful / total * 100, 1) if total else 0.0
    return {"total": total, "useful": useful, "useless": total - useful, "useful_rate": int(rate)}
