# 107-Agent Dockerfile
# 多阶段构建，优化镜像大小

# ── 阶段 1: 构建依赖 ──
FROM python:3.11-slim AS builder

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖配置
COPY pyproject.toml ./

# 安装依赖到指定目录
RUN pip install --prefix=/install --no-cache-dir .

# ── 阶段 2: 运行时镜像 ──
FROM python:3.11-slim

WORKDIR /app

# 创建非 root 用户
RUN useradd --create-home --shell /bin/bash appuser

# 从构建阶段复制依赖
COPY --from=builder /install /usr/local

# 复制源代码
COPY src/ ./src/
COPY .env.example ./.env.example

# 创建数据目录
RUN mkdir -p /app/data/chroma && chown -R appuser:appuser /app

# 切换到非 root 用户
USER appuser

# 环境变量
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')"

# 启动命令
CMD ["python", "src/main.py"]
