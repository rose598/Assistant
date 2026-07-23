# 使用指南

本文档介绍 107-Agent 项目的基本使用方法和开发操作。

## 目录

- [环境配置](#环境配置)
- [运行服务](#运行服务)
- [运行测试](#运行测试)
- [新增 FAQ 条目](#新增-faq-条目)
- [代码检查与格式化](#代码检查与格式化)
- [常见问题](#常见问题)

---

## 环境配置

### 1. 安装依赖

```bash
# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 安装开发依赖
pip install -e ".[dev]"
```

### 2. 配置环境变量

```bash
# 复制模板
cp .env.example .env

# 编辑 .env 文件，填写实际配置
# 必填项：LLM_API_KEY, SSH_HOST, SSH_USER 等
```

### 3. 安装 pre-commit hooks

```bash
pre-commit install
```

安装后，每次 commit 会自动运行代码检查和格式化。

---

## 运行服务

### 开发模式

```bash
python src/main.py
```

服务将在 `http://localhost:8000` 启动。

### API 文档

启动服务后访问：
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## 运行测试

### 运行所有测试

```bash
pytest
```

### 运行特定模块测试

```bash
# 知识库模块测试
pytest tests/test_knowledge/

# 意图识别模块测试
pytest tests/test_intent/

# 日志分析模块测试
pytest tests/test_log_analysis/
```

### 显示测试覆盖率

```bash
# 生成 HTML 覆盖率报告
pytest --cov=src --cov-report=html

# 查看报告：打开 htmlcov/index.html
```

### 运行并输出详细信息

```bash
pytest -v -s
```

---

## 新增 FAQ 条目

### 1. 确定分类

参考知识库分类体系：

| 一级类 | 二级类 | 说明 |
|--------|--------|------|
| error_diagnosis | qos_limit | QOS 限制相关错误 |
| error_diagnosis | gpu_related | GPU 相关问题 |
| error_diagnosis | oom | 内存溢出问题 |
| error_diagnosis | script_error | 脚本错误 |
| error_diagnosis | env_missing | 环境缺失 |
| job_submission | interactive | 交互式作业 |
| job_submission | batch | 批处理作业 |
| job_status | queuing | 排队状态 |
| permission | quota | 配额限制 |

### 2. 编写 JSON 条目

在对应的 JSON 文件中添加条目：

```json
{
  "id": "faq-xxx",
  "category": "error_diagnosis",
  "title": "问题标题",
  "keywords": ["关键词1", "关键词2"],
  "intents": ["意图标签1"],
  "question": "用户可能问的问题？",
  "answer": "详细的回答内容。",
  "related_errors": [],
  "references": []
}
```

### 3. 知识库文件位置

- 报错类：`src/knowledge/data/faq_errors.json`
- 使用类：`src/knowledge/data/faq_usage.json`
- 命令类：`src/knowledge/data/slurm_commands.json`
- QOS 类：`src/knowledge/data/qos_table.json`
- 错误码：`src/knowledge/data/error_codes.json`

### 4. 验证

```bash
# 验证 JSON 格式
python -c "import json; json.load(open('src/knowledge/data/faq_errors.json'))"

# 运行知识库测试
pytest tests/test_knowledge/ -v
```

---

## 代码检查与格式化

### 手动运行 Ruff

```bash
# 检查代码
ruff check src/ tests/

# 自动修复
ruff check --fix src/ tests/

# 格式化代码
ruff format src/ tests/
```

### 手动运行 mypy

```bash
mypy src/ --ignore-missing-imports
```

### 运行 pre-commit

```bash
# 对所有文件运行
pre-commit run --all-files

# 仅对暂存文件运行
pre-commit run
```

---

## 常见问题

### Q: 如何添加新的 API 端点？

A: 在 `src/api/` 目录下创建新的路由文件，参考 `routes_ask.py` 的结构：

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/your-endpoint")
async def your_endpoint():
    return {"message": "Hello"}
```

然后在 `src/main.py` 中注册路由。

### Q: 如何调试 LLM 调用？

A: 设置环境变量 `DEBUG=true`，然后查看日志输出。也可以直接调用 LLM 客户端测试：

```python
from src.llm.client import LLMClient

client = LLMClient()
response = client.chat("你好")
print(response)
```

### Q: 如何测试 SSH 连接？

A: 使用测试脚本：

```python
from src.log_analysis.ssh_client import SSHClient

async def test():
    client = SSHClient()
    result = await client.execute("squeue -u $USER")
    print(result)
```

### Q: 知识库更新后需要重启服务吗？

A: 不需要。知识库支持热加载，修改 JSON 文件后会自动生效。

### Q: 如何查看当前配置？

A: 导入配置模块查看：

```python
from src import config

print(f"LLM Model: {config.LLM_MODEL}")
print(f"Debug: {config.DEBUG}")
```

---

## 项目结构说明

```
107-agent/
├── src/                    # 源代码
│   ├── main.py             # FastAPI 入口
│   ├── config.py           # 配置管理（所有配置集中在此）
│   ├── knowledge/          # 知识库模块
│   │   ├── loader.py       # 知识库加载器
│   │   ├── schema.py       # 数据类型定义
│   │   ├── matcher.py      # 关键词匹配引擎
│   │   └── data/           # 知识库 JSON 文件
│   ├── intent/             # 意图识别引擎
│   │   ├── classifier.py   # 意图分类器
│   │   ├── keywords.py     # 关键词映射表
│   │   └── rules.py        # 规则模板
│   ├── log_analysis/       # 日志分析模块
│   │   ├── ssh_client.py   # SSH 连接封装
│   │   ├── job_query.py    # 作业查询接口
│   │   ├── log_parser.py   # 日志解析器
│   │   └── error_classifier.py  # 错误分类器
│   ├── llm/                # LLM 集成
│   │   ├── client.py       # LLM API 客户端
│   │   ├── prompts.py      # Prompt 模板
│   │   ├── embedding.py    # 向量嵌入
│   │   ├── vector_store.py # 向量数据库
│   │   └── rag_engine.py   # RAG 引擎
│   ├── monitor/            # 监控与推送
│   │   ├── queue_monitor.py     # 队列监控
│   │   ├── idle_detector.py     # 空闲检测
│   │   └── notifier.py          # 推送通知
│   ├── dialog/             # 多轮对话管理
│   │   ├── session.py      # 会话管理
│   │   └── state_machine.py # 对话状态机
│   ├── script/             # sbatch 脚本处理
│   │   ├── parser.py       # 脚本解析器
│   │   ├── templates.py    # 脚本模板
│   │   └── generator.py    # 脚本生成
│   ├── recommender/        # 资源推荐引擎
│   │   ├── task_classifier.py   # 任务分类
│   │   ├── partition_rank.py    # 分区排序
│   │   └── combined.py          # 综合推荐
│   ├── api/                # API 路由
│   │   ├── routes_ask.py   # 问答接口
│   │   ├── routes_jobs.py  # 作业查询接口
│   │   └── websocket.py    # WebSocket
│   └── frontend/           # 前端界面
│       ├── index.html      # 聊天界面
│       ├── styles.css      # 样式
│       └── scripts.js      # JS 逻辑
├── tests/                  # 测试代码
├── docs/                   # 文档
├── scripts/                # 工具脚本
└── docker/                 # Docker 部署
```

---

## 相关文档

- [CONTRIBUTING.md](../CONTRIBUTING.md) - 贡献指南
- [README.md](../README.md) - 项目说明
- [deploy.md](./deploy.md) - 部署指南（待编写）
- [api.md](./api.md) - API 文档（待编写）
