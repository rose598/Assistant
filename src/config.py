"""107 算力平台答疑智能体 — 配置管理模块."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

# 项目根目录
BASE_DIR: Path = Path(__file__).resolve().parent.parent

# 环境变量加载
_env_file: dict[str, str | None] = dotenv_values(BASE_DIR / ".env")


def _get(key: str, default: Any = None) -> Any:
    """从环境变量或 .env 文件获取配置值."""
    return os.getenv(key, _env_file.get(key, default))


# ──────────────────────────────────────────────
# 应用基础配置
# ──────────────────────────────────────────────
APP_NAME: str = "107-agent"
APP_VERSION: str = "0.1.0"
DEBUG: bool = _get("DEBUG", "true").lower() == "true"

# 服务配置
HOST: str = _get("HOST", "0.0.0.0")
PORT: int = int(_get("PORT", "8000"))

# ──────────────────────────────────────────────
# 数据库配置
# ──────────────────────────────────────────────
DATABASE_URL: str = _get(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'app.db'}",
)

# ──────────────────────────────────────────────
# Redis 配置（可选，生产环境使用）
# ──────────────────────────────────────────────
REDIS_URL: str = _get("REDIS_URL", "redis://localhost:6379/0")
SESSION_TTL: int = int(_get("SESSION_TTL", "3600"))  # 会话过期时间（秒）

# ──────────────────────────────────────────────
# LLM API 配置
# ──────────────────────────────────────────────
LLM_API_BASE: str = _get("LLM_API_BASE", "https://api.openai.com/v1")
LLM_API_KEY: str = _get("LLM_API_KEY", "")
LLM_MODEL: str = _get("LLM_MODEL", "qwen2.5-7b")
LLM_TIMEOUT: int = int(_get("LLM_TIMEOUT", "60"))
LLM_MAX_RETRIES: int = int(_get("LLM_MAX_RETRIES", "3"))
LLM_CACHE_TTL: int = int(_get("LLM_CACHE_TTL", "1800"))  # 缓存30分钟

# ──────────────────────────────────────────────
# SSH 连接配置
# ──────────────────────────────────────────────
SSH_HOST: str = _get("SSH_HOST", "")
SSH_PORT: int = int(_get("SSH_PORT", "22"))
SSH_USER: str = _get("SSH_USER", "")
SSH_KEY_PATH: str = _get("SSH_KEY_PATH", "")
SSH_TIMEOUT: int = int(_get("SSH_TIMEOUT", "30"))
SSH_MAX_RETRIES: int = int(_get("SSH_MAX_RETRIES", "3"))

# ──────────────────────────────────────────────
# 向量数据库配置
# ──────────────────────────────────────────────
CHROMA_PERSIST_DIR: str = _get(
    "CHROMA_PERSIST_DIR",
    str(BASE_DIR / "data" / "chroma"),
)
EMBEDDING_MODEL: str = _get("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
CHUNK_SIZE: int = int(_get("CHUNK_SIZE", "256"))
CHUNK_OVERLAP: int = int(_get("CHUNK_OVERLAP", "32"))

# ──────────────────────────────────────────────
# 知识库配置
# ──────────────────────────────────────────────
KNOWLEDGE_DIR: Path = BASE_DIR / "src" / "knowledge" / "data"
INTENT_THRESHOLD: float = float(_get("INTENT_THRESHOLD", "0.6"))

# ──────────────────────────────────────────────
# 监控与推送配置
# ──────────────────────────────────────────────
SCHEDULER_QUEUE_INTERVAL: str = "*/10 * * * *"  # 每10分钟
SCHEDULER_IDLE_INTERVAL: str = "*/15 * * * *"  # 每15分钟
SCHEDULER_JOB_INTERVAL: str = "*/5 * * * *"  # 每5分钟
SCHEDULER_PREDICTION_INTERVAL: str = "0 */1 * * *"  # 每小时

QUEUE_CONGEST_THRESHOLD: int = 20  # 排队数阈值
QUEUE_WAIT_THRESHOLD: int = 30  # 平均等待时间阈值（分钟）
IDLE_GPU_RATIO_THRESHOLD: float = 0.6  # 空闲GPU节点占比阈值

# ──────────────────────────────────────────────
# 推送通道配置
# ──────────────────────────────────────────────
WECHAT_BOT_WEBHOOK: str = _get("WECHAT_BOT_WEBHOOK", "")
SMTP_HOST: str = _get("SMTP_HOST", "")
SMTP_PORT: int = int(_get("SMTP_PORT", "465"))
SMTP_USER: str = _get("SMTP_USER", "")
SMTP_PASSWORD: str = _get("SMTP_PASSWORD", "")

# ──────────────────────────────────────────────
# 安全配置
# ──────────────────────────────────────────────
API_RATE_LIMIT: int = int(_get("API_RATE_LIMIT", "100"))  # 每分钟请求数
CORS_ORIGINS: list[str] = _get("CORS_ORIGINS", "*").split(",")
