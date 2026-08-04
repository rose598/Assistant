# 部署指南

本文档介绍如何部署 107-Agent 算力平台答疑智能体。

---

## 目录

1. [环境要求](#环境要求)
2. [本地部署](#本地部署)
3. [Docker 部署](#docker-部署)
4. [Docker Compose 部署](#docker-compose-部署)
5. [生产环境配置](#生产环境配置)
6. [监控与日志](#监控与日志)
7. [故障排查](#故障排查)

---

## 环境要求

### 最低配置

| 资源 | 要求 |
|------|------|
| CPU | 2 核 |
| 内存 | 4 GB |
| 磁盘 | 20 GB |
| Python | 3.10+ |
| Docker | 24.0+（可选） |

### 推荐配置（生产环境）

| 资源 | 要求 |
|------|------|
| CPU | 4 核 |
| 内存 | 8 GB |
| 磁盘 | 50 GB SSD |
| Redis | 6.0+ |
| PostgreSQL | 14+（可选） |

---

## 本地部署

### 1. 克隆代码

```bash
git clone https://github.com/rose598/Assistant.git
cd Assistant
```

### 2. 创建虚拟环境

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -e ".[dev]"
```

### 4. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填写必要配置：

```bash
# 必填项
LLM_API_KEY=your-api-key-here
SSH_HOST=107.ustc.edu.cn
SSH_USER=your-username
SSH_KEY_PATH=~/.ssh/id_rsa

# 可选项（有默认值）
DEBUG=true
PORT=8000
```

### 5. 初始化数据目录

```bash
mkdir -p data/chroma
```

### 6. 启动服务

```bash
python src/main.py
```

服务将在 `http://localhost:8000` 启动。

### 7. 验证部署

```bash
# 健康检查
curl http://localhost:8000/health

# 测试问答
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "如何提交作业？"}'
```

---

## Docker 部署

### 1. 构建镜像

```bash
docker build -t 107-agent:latest -f docker/Dockerfile .
```

### 2. 运行容器

```bash
docker run -d \
  --name 107-agent \
  -p 8000:8000 \
  -e LLM_API_KEY=your-api-key \
  -e SSH_HOST=107.ustc.edu.cn \
  -e SSH_USER=your-username \
  -v 107-agent-data:/app/data \
  107-agent:latest
```

### 3. 查看日志

```bash
docker logs -f 107-agent
```

### 4. 停止容器

```bash
docker stop 107-agent
docker rm 107-agent
```

---

## Docker Compose 部署

### 1. 准备 docker-compose.yml

```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: docker/Dockerfile
    ports:
      - "8000:8000"
    environment:
      - LLM_API_KEY=${LLM_API_KEY}
      - SSH_HOST=${SSH_HOST}
      - SSH_USER=${SSH_USER}
      - SSH_KEY_PATH=/app/keys/id_rsa
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - app-data:/app/data
      - ./keys:/app/keys:ro
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
    restart: unless-stopped

volumes:
  app-data:
  redis-data:
```

### 2. 启动服务

```bash
# 创建 SSH 密钥目录
mkdir -p keys
cp ~/.ssh/id_rsa keys/
chmod 600 keys/id_rsa

# 启动
docker-compose up -d

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f app
```

### 3. 停止服务

```bash
docker-compose down
```

### 4. 更新部署

```bash
# 拉取最新代码
git pull

# 重新构建并启动
docker-compose up -d --build
```

---

## 生产环境配置

### 1. 使用 PostgreSQL

```bash
# 安装 PostgreSQL
docker run -d \
  --name postgres \
  -e POSTGRES_USER=agent \
  -e POSTGRES_PASSWORD=your-password \
  -e POSTGRES_DB=agent107 \
  -v postgres-data:/var/lib/postgresql/data \
  postgres:15-alpine
```

配置 `.env`:

```bash
DATABASE_URL=postgresql+asyncpg://agent:your-password@localhost:5432/agent107
```

### 2. 使用 Redis 集群

```bash
# 生产环境建议使用 Redis Sentinel 或 Cluster
# 这里展示单机配置
REDIS_URL=redis://:password@redis-server:6379/0
```

### 3. Nginx 反向代理

```nginx
server {
    listen 80;
    server_name agent.107.ustc.edu.cn;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # WebSocket 支持
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 4. SSL/HTTPS

```bash
# 使用 certbot 申请 Let's Encrypt 证书
certbot --nginx -d agent.107.ustc.edu.cn
```

---

## 监控与日志

### 日志位置

| 环境 | 日志位置 |
|------|----------|
| 本地开发 | 控制台输出 |
| Docker | `docker logs 107-agent` |
| 生产环境 | `/var/log/107-agent/` |

### 日志级别配置

```bash
# .env
LOG_LEVEL=INFO  # DEBUG/INFO/WARNING/ERROR
```

### 健康检查端点

```bash
# 基础健康检查
GET /health

# 详细状态检查
GET /health/detailed
```

### Prometheus 监控（可选）

```python
# 在 main.py 中添加
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)
```

---

## 故障排查

### 服务无法启动

**症状**: `python src/main.py` 报错

**排查步骤**:

1. 检查 Python 版本：
   ```bash
   python --version  # 需要 3.10+
   ```

2. 检查依赖安装：
   ```bash
   pip list | grep fastapi
   ```

3. 检查配置文件：
   ```bash
   cat .env
   ```

4. 检查端口占用：
   ```bash
   # Windows
   netstat -ano | findstr :8000

   # Linux
   lsof -i :8000
   ```

### SSH 连接失败

**症状**: 日志中出现 `SSH connection failed`

**排查步骤**:

1. 验证 SSH 密钥：
   ```bash
   ssh -i ~/.ssh/id_rsa user@107.ustc.edu.cn
   ```

2. 检查 `.env` 配置：
   ```bash
   SSH_HOST=107.ustc.edu.cn
   SSH_USER=your-username
   SSH_KEY_PATH=~/.ssh/id_rsa
   ```

3. 检查防火墙设置

### LLM API 调用失败

**症状**: 问答响应超时或错误

**排查步骤**:

1. 验证 API Key 有效：
   ```bash
   curl -H "Authorization: Bearer $LLM_API_KEY" $LLM_API_BASE/models
   ```

2. 检查网络连通性：
   ```bash
   curl $LLM_API_BASE
   ```

3. 查看超时配置：
   ```bash
   LLM_TIMEOUT=60  # 增加超时时间
   ```

### 向量数据库错误

**症状**: `ChromaDB connection error`

**排查步骤**:

1. 检查数据目录权限：
   ```bash
   ls -la data/chroma
   ```

2. 删除损坏的索引重建：
   ```bash
   rm -rf data/chroma
   python scripts/seed_knowledge.py
   ```

---

## 备份与恢复

### 数据备份

```bash
# 备份数据目录
tar -czf backup-$(date +%Y%m%d).tar.gz data/

# Docker 环境
docker run --rm \
  -v 107-agent-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/backup.tar.gz /data
```

### 数据恢复

```bash
# 解压备份
tar -xzf backup-20240101.tar.gz

# 重启服务
docker-compose restart app
```

---

## 更新流程

### 1. 备份当前数据

```bash
tar -czf backup-before-update.tar.gz data/
```

### 2. 拉取最新代码

```bash
git pull origin main
```

### 3. 重新构建

```bash
# Docker Compose
docker-compose up -d --build

# 或本地
pip install -e ".[dev]"
```

### 4. 验证部署

```bash
curl http://localhost:8000/health
pytest tests/ -v
```

### 5. 回滚（如需要）

```bash
# 恢复备份
tar -xzf backup-before-update.tar.gz

# 回滚代码
git checkout <previous-commit>

# 重启服务
docker-compose restart
```

---

## 支持

遇到问题请：

1. 查看日志定位问题
2. 搜索项目 Issues
3. 创建新 Issue 描述问题
