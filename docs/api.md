# API 文档

本文档描述 107-Agent 算力平台答疑智能体的 REST API 接口。

**Base URL**: `http://localhost:8000`

**API 文档自动生成**: 启动服务后访问
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

---

## 目录

1. [问答接口](#问答接口)
2. [作业查询接口](#作业查询接口)
3. [作业诊断接口](#作业诊断接口)
4. [订阅管理接口](#订阅管理接口)
5. [反馈接口](#反馈接口)
6. [健康检查](#健康检查)

---

## 问答接口

### POST /api/ask

提交自然语言问题，返回智能回答。

**请求体**:

```json
{
  "question": "为什么我的作业报 QOSMaxWallDurationPerJobLimit？",
  "session_id": "可选的会话ID，用于多轮对话",
  "user": "可选的用户名"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| question | string | ✅ | 用户问题，长度 1-5000 字符 |
| session_id | string | ❌ | 会话ID，用于保持多轮对话上下文 |
| user | string | ❌ | 用户名，用于个性化回答 |

**响应 200**:

```json
{
  "answer": "这个错误表示作业申请的运行时间超过当前 QOS 允许的最长时间...\n\n**解决步骤**：\n1. 检查脚本中的 `#SBATCH -t`\n2. 默认 QOS 为 4 小时",
  "confidence": 0.95,
  "sources": [
    {
      "id": "faq-001",
      "title": "QOSMaxWallDurationPerJobLimit",
      "category": "error_qos"
    }
  ],
  "session_id": "abc123",
  "intent": "error_diagnosis"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| answer | string | 回答内容，Markdown 格式 |
| confidence | float | 置信度 0.0-1.0 |
| sources | array | 引用的知识库来源 |
| session_id | string | 会话ID |
| intent | string | 识别的意图 |

**错误响应**:

| 状态码 | 说明 |
|--------|------|
| 400 | question 为空或超长 |
| 429 | 请求过于频繁 |
| 500 | 服务器内部错误 |

---

**curl 示例**:

```bash
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "CUDA out of memory 怎么办？"}'
```

**Python 示例**:

```python
import httpx

async def ask_question(question: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/ask",
            json={"question": question},
        )
        return response.json()

# 使用
result = await ask_question("为什么作业一直排队？")
print(result["answer"])
```

---

## 作业查询接口

### GET /api/jobs/{user}

查询指定用户的最近作业列表。

**路径参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| user | string | 用户名 |

**查询参数**:

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| limit | int | 10 | 返回的最大条数 |
| days | int | 7 | 查询最近多少天的作业 |

**响应 200**:

```json
{
  "user": "scc123",
  "jobs": [
    {
      "job_id": "12345",
      "job_name": "train_resnet",
      "state": "COMPLETED",
      "partition": "Students",
      "qos": "qos_stu_default",
      "submit_time": "2024-01-01T10:00:00",
      "start_time": "2024-01-01T10:05:00",
      "end_time": "2024-01-01T12:30:00",
      "exit_code": "0:0"
    }
  ],
  "total": 5
}
```

---

**curl 示例**:

```bash
curl http://localhost:8000/api/jobs/scc123?limit=5&days=3
```

**Python 示例**:

```python
import httpx

async def get_user_jobs(user: str, limit: int = 10) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"http://localhost:8000/api/jobs/{user}",
            params={"limit": limit},
        )
        return response.json()
```

---

## 作业诊断接口

### GET /api/jobs/{job_id}/diagnose

诊断指定作业的失败原因。

**路径参数**:

| 参数 | 类型 | 说明 |
|------|------|------|
| job_id | string | 作业ID |

**响应 200**:

```json
{
  "job_id": "12345",
  "status": "FAILED",
  "diagnosis": {
    "category": "resource_exhausted",
    "subcategory": "gpu_oom",
    "confidence": 0.92,
    "description": "作业因 GPU 显存不足而失败",
    "error_log": "CUDA out of memory. Tried to allocate 2.00 GiB"
  },
  "suggestions": [
    {
      "action": "减小 batch_size",
      "command": "# 修改脚本中的 batch_size 参数\npython train.py --batch-size 32",
      "priority": "high"
    }
  ],
  "related_faq": [
    {
      "id": "faq-003",
      "title": "CUDA out of memory 解决方法"
    }
  ]
}
```

---

**curl 示例**:

```bash
curl http://localhost:8000/api/jobs/12345/diagnose
```

---

## 订阅管理接口

### POST /api/subscription

创建推送订阅。

**请求体**:

```json
{
  "user": "scc123",
  "channels": ["wechat", "email"],
  "events": ["queue_alert", "idle_notify", "job_complete"],
  "wechat_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
  "email": "user@ustc.edu.cn"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user | string | ✅ | 用户名 |
| channels | array | ✅ | 推送通道：wechat/email/websocket |
| events | array | ✅ | 订阅事件类型 |
| wechat_webhook | string | ❌ | 企业微信 Webhook URL |
| email | string | ❌ | 邮箱地址 |

### GET /api/subscription/{user}

查询用户订阅信息。

### PUT /api/subscription/{user}

更新用户订阅。

### DELETE /api/subscription/{user}

删除用户订阅。

---

## 反馈接口

### POST /api/feedback

提交回答反馈。

**请求体**:

```json
{
  "session_id": "abc123",
  "question": "原始问题",
  "answer": "回答内容",
  "rating": "helpful",
  "comment": "可选的详细反馈"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | ✅ | 会话ID |
| rating | string | ✅ | helpful / not_helpful |
| comment | string | ❌ | 详细反馈 |

---

## 健康检查

### GET /health

检查服务健康状态。

**响应 200**:

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 3600,
  "services": {
    "database": "connected",
    "llm": "available",
    "ssh": "connected"
  }
}
```

---

## 错误响应格式

所有错误响应遵循统一格式：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "question 字段不能为空",
    "details": {
      "field": "question",
      "constraint": "required"
    }
  }
}
```

**常见错误码**:

| 错误码 | HTTP 状态 | 说明 |
|--------|-----------|------|
| VALIDATION_ERROR | 400 | 请求参数验证失败 |
| UNAUTHORIZED | 401 | 未授权 |
| FORBIDDEN | 403 | 权限不足 |
| NOT_FOUND | 404 | 资源不存在 |
| RATE_LIMITED | 429 | 请求过于频繁 |
| INTERNAL_ERROR | 500 | 服务器内部错误 |

---

## WebSocket 接口

### WS /ws/chat

实时对话 WebSocket 连接。

**连接**: `ws://localhost:8000/ws/chat`

**消息格式**:

```json
// 客户端发送
{"type": "message", "content": "你好", "session_id": "abc123"}

// 服务端响应（流式）
{"type": "token", "content": "你"}
{"type": "token", "content": "好"}
{"type": "done", "content": "你好！有什么可以帮你的？"}
```

---

## 认证

当前版本 API 无需认证，生产环境将添加：
- API Key 认证（Header: `X-API-Key`）
- 或 JWT Token 认证（Header: `Authorization: Bearer <token>`）

---

## 限流

- 默认限流：100 请求/分钟/IP
- 超限返回 429 状态码

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.1.0 | 2024-01-01 | 初始版本，包含基础问答和作业查询 |
