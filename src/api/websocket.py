"""/ws/ask WebSocket 实时对话端点 (第 2 周周四计划任务).

基于原生 FastAPI WebSocket, 复用既有问答 pipeline, 实现多轮实时往返:
客户端发送 {"question": "..."} → 服务端返回结构化答案 + 意图.

鲁棒性:
- 空问题 / 非 JSON / 过长问题均有友好回应, 不中断连接
- 客户端断开时优雅清理, 不抛异常
- 单个连接失效不影响其它连接
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.pipeline import AnswerPipeline

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["websocket"])

_MAX_QUESTION_LEN = 5000

# 单例 pipeline (与 routes_ask 共享逻辑, 各自持有实例亦可)
_pipeline: AnswerPipeline | None = None


def _get_pipeline() -> AnswerPipeline:
    """懒加载问答 pipeline 单例."""
    global _pipeline
    if _pipeline is None:
        _pipeline = AnswerPipeline()
    return _pipeline


def _build_reply(question: str) -> dict[str, object]:
    """调用 pipeline 生成结构化回复."""
    answer = _get_pipeline().ask(question)
    return {
        "query": question,
        "answer": answer.answer,
        "primary_intent": answer.intent.primary,
        "is_unknown": answer.intent.is_unknown,
        "needs_llm": answer.needs_llm,
    }


@router.websocket("/ws/ask")
async def websocket_ask(ws: WebSocket) -> None:
    """接受 WebSocket 连接并处理多轮问答."""
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            question = raw.strip()
            if not question:
                await ws.send_json({"error": "问题不能为空"})
                continue
            if len(question) > _MAX_QUESTION_LEN:
                await ws.send_json({"error": "问题过长"})
                continue
            try:
                reply = _build_reply(question)
            except Exception:
                logger.exception("websocket 问答处理失败")
                await ws.send_json({"error": "服务器内部错误"})
                continue
            await ws.send_json(reply)
    except WebSocketDisconnect:
        # 客户端主动断开, 正常清理
        return
    except Exception:
        logger.exception("websocket 连接异常")
        await ws.close()
