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


# ──────────────────────────────────────────────
# 对象式配置访问（get_config）
# ──────────────────────────────────────────────
# 说明：第 3 周 client.py / ssh_client.py 使用对象式访问（``get_config().llm_base_url``），
# 而 D 已上传的 config.py 为模块级字段。此处提供统一对象，读取同一批环境变量，
# 二者兼容（真实平台变量为 AGENT_LLM_*，模块级 LLM_* 作为回退，避免破坏既有调用）。


class Config:
    """对象式配置访问封装。

    支持两种用法（保持与 D 共享文件 + 第 3 周测试兼容）：
    - ``Config(llm_base_url=..., llm_api_key=..., ...)`` 显式传参（测试/覆盖用），
      未传的字段回退到环境变量 / .env。
    - ``get_config()`` 返回已由环境变量填充的单例（client.py / ssh_client.py 用）。
    """

    def __init__(
        self,
        llm_base_url: str | None = None,
        llm_api_key: str | None = None,
        llm_model: str | None = None,
        llm_timeout: int | None = None,
        llm_retry: int | None = None,
        llm_temperature: float | None = None,
        llm_max_tokens: int | None = None,
        ssh_host: str | None = None,
        ssh_user: str | None = None,
        ssh_port: int | None = None,
        ssh_timeout: int | None = None,
        ssh_retry: int | None = None,
        max_sessions: int | None = None,
        cors_origins: list[str] | None = None,
        knowledge_faq_path: str | None = None,
        knowledge_commands_path: str | None = None,
        knowledge_qos_path: str | None = None,
        knowledge_error_codes_path: str | None = None,
        top_k_retrieve: int | None = None,
        fuzzy_match_threshold: int | None = None,
        intent_keyword_threshold: float | None = None,
        intent_llm_fallback_threshold: float | None = None,
        rule_conf_threshold: float | None = None,
        llm_conf_threshold: float | None = None,
        idle_gpu_ratio_threshold: float | None = None,
        prediction_window_secs: int | None = None,
        prediction_cold_start: float | None = None,
        queue_congest_threshold: int | None = None,
        queue_wait_threshold: float | None = None,
    ) -> None:
        # LLM: 真实平台变量 AGENT_LLM_* 优先，回退到模块级 LLM_*
        self.llm_base_url = (
            llm_base_url if llm_base_url is not None
            else _get("AGENT_LLM_BASE_URL", _get("LLM_API_BASE", ""))
        )
        self.llm_api_key = (
            llm_api_key if llm_api_key is not None
            else _get("AGENT_LLM_API_KEY", _get("LLM_API_KEY", ""))
        )
        self.llm_model = (
            llm_model if llm_model is not None
            else _get("AGENT_LLM_MODEL", _get("LLM_MODEL", "qwen2.5-7b"))
        )
        self.llm_timeout = (
            llm_timeout if llm_timeout is not None
            else int(_get("AGENT_LLM_TIMEOUT", _get("LLM_TIMEOUT", "60")))
        )
        self.llm_retry = (
            llm_retry if llm_retry is not None
            else int(_get("AGENT_LLM_MAX_RETRIES", _get("LLM_MAX_RETRIES", "3")))
        )
        self.llm_temperature = (
            llm_temperature if llm_temperature is not None
            else float(_get("AGENT_LLM_TEMPERATURE", _get("LLM_TEMPERATURE", "0.3")))
        )
        self.llm_max_tokens = (
            llm_max_tokens if llm_max_tokens is not None
            else int(_get("AGENT_LLM_MAX_TOKENS", _get("LLM_MAX_TOKENS", "1024")))
        )
        # SSH
        self.ssh_host = ssh_host if ssh_host is not None else _get("SSH_HOST", "")
        self.ssh_user = ssh_user if ssh_user is not None else _get("SSH_USER", "")
        self.ssh_port = (
            ssh_port if ssh_port is not None else int(_get("SSH_PORT", "22"))
        )
        self.ssh_timeout = (
            ssh_timeout if ssh_timeout is not None
            else int(_get("SSH_TIMEOUT", "30"))
        )
        self.ssh_retry = (
            ssh_retry if ssh_retry is not None
            else int(_get("SSH_MAX_RETRIES", "3"))
        )
        # 会话
        self.max_sessions = (
            max_sessions if max_sessions is not None
            else int(_get("MAX_SESSIONS", "200"))
        )
        # Web
        self.cors_origins = (
            cors_origins if cors_origins is not None
            else [o.strip() for o in _get("CORS_ORIGINS", "*").split(",") if o.strip()]
        )
        # 知识库
        self.data_dir = KNOWLEDGE_DIR
        self.knowledge_faq_path = (
            knowledge_faq_path if knowledge_faq_path is not None
            else _get("KNOW_FILENAME", "faq_errors.json")
        )
        self.knowledge_commands_path = (
            knowledge_commands_path if knowledge_commands_path is not None
            else _get("KNOW_COMMANDS_FILENAME", "slurm_commands.json")
        )
        self.knowledge_qos_path = (
            knowledge_qos_path if knowledge_qos_path is not None
            else _get("KNOW_QOS_FILENAME", "qos_table.json")
        )
        self.knowledge_error_codes_path = (
            knowledge_error_codes_path if knowledge_error_codes_path is not None
            else _get("KNOW_ERROR_CODES_FILENAME", "error_codes.json")
        )
        # 检索 / 匹配参数
        self.top_k_retrieve = (
            top_k_retrieve if top_k_retrieve is not None
            else int(_get("TOP_K_RETRIEVE", "5"))
        )
        self.fuzzy_match_threshold = (
            fuzzy_match_threshold if fuzzy_match_threshold is not None
            else int(_get("FUZZY_MATCH_THRESHOLD", "60"))
        )
        # 意图阈值
        self.intent_keyword_threshold = (
            intent_keyword_threshold if intent_keyword_threshold is not None
            else float(_get("INTENT_THRESHOLD", "0.6"))
        )
        self.intent_llm_fallback_threshold = (
            intent_llm_fallback_threshold if intent_llm_fallback_threshold is not None
            else float(_get("INTENT_LLM_THRESHOLD", "0.3"))
        )
        # 日志分类阈值（规则优先 + LLM 兜底）
        self.rule_conf_threshold = (
            rule_conf_threshold if rule_conf_threshold is not None
            else float(_get("RULE_CONF_THRESHOLD", "0.6"))
        )
        self.llm_conf_threshold = (
            llm_conf_threshold if llm_conf_threshold is not None
            else float(_get("LLM_CONF_THRESHOLD", "0.5"))
        )
        # 监控/预测（第 4 周周二 idle_detector / prediction）
        self.idle_gpu_ratio_threshold = (
            idle_gpu_ratio_threshold if idle_gpu_ratio_threshold is not None
            else float(_get("IDLE_GPU_RATIO_THRESHOLD", "0.6"))
        )
        self.prediction_window_secs = (
            prediction_window_secs if prediction_window_secs is not None
            else int(_get("PREDICTION_WINDOW_SECS", str(7 * 86400)))
        )
        self.prediction_cold_start = (
            prediction_cold_start if prediction_cold_start is not None
            else float(_get("PREDICTION_COLD_START", "0.5"))
        )
        # 排队拥堵预警（第 4 周 queue_monitor）：排队数 > 阈值 或 平均等待 > 阈值(分钟)
        self.queue_congest_threshold = (
            queue_congest_threshold if queue_congest_threshold is not None
            else int(_get("QUEUE_CONGEST_THRESHOLD", "20"))
        )
        self.queue_wait_threshold = (
            queue_wait_threshold if queue_wait_threshold is not None
            else float(_get("QUEUE_WAIT_THRESHOLD", "30"))
        )

    def resolve_path(self, path: str | Path) -> Path:
        """解析知识库路径（相对/绝对均可），返回绝对 Path。"""
        p = Path(path)
        return p if p.is_absolute() else p.resolve()


_config: Config | None = None


def get_config() -> Config:
    """获取全局配置对象单例（懒加载）。"""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config() -> None:
    """重置配置单例（测试隔离用）。"""
    global _config
    _config = None
