"""FastAPI 应用入口.

启动方式:
    uvicorn src.main:app --reload

提供:
- CORS 中间件(由 config.cors_origins 控制)
- 请求日志中间件(记录 method/path/status/耗时)
- 全局异常处理(未捕获异常返回 500, 不泄露堆栈)
- /health 健康检查
- /api/ask 问答端点(含 /api/ask/stream SSE 流式)
- /api/jobs 作业查询与诊断端点
- /api/feedback 反馈收集
- /ws/ask WebSocket 实时对话
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from src.api.routes_ask import router as ask_router
from src.api.routes_feedback import router as feedback_router
from src.api.routes_flow import router as flow_router
from src.api.routes_jobs import router as jobs_router
from src.api.routes_script import router as script_router
from src.api.websocket import router as ws_router
from src.config import get_config

logger = logging.getLogger("uvicorn.error")

config = get_config()

app = FastAPI(
    title="107-Agent API",
    version="0.1.0",
    description="USTC 本科生算力平台答疑智能体",
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=False,  # 开发阶段 allow_origins=["*"] 时不能开启 credentials
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- 请求日志中间件 ----
@app.middleware("http")
async def request_logging(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """记录请求方法与路径、状态码与耗时."""
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("处理请求异常: %s %s", request.method, request.url.path)
        raise
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %s (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


# ---- 全局异常处理 ----
@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """未捕获异常统一返回 500, 不泄露堆栈细节."""
    logger.exception("未捕获异常: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


# ---- 路由 ----
app.include_router(ask_router)
app.include_router(jobs_router)
app.include_router(feedback_router)
app.include_router(ws_router)
app.include_router(flow_router)
app.include_router(script_router)


# ---- 健康检查 ----
@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


# ---- 前端静态资源(最后挂载, 避免遮蔽 /api/*) ----
_frontend_dir = Path(__file__).resolve().parent / "frontend"
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
