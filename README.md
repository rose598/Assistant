# 107-Agent — 算力平台答疑智能体

USTC 本科生算力平台（107.ustc.edu.cn）智能答疑助手，基于 Slurm 调度系统，为本科生提供 GPU/CPU 共享计算资源的智能问答服务。

## 项目简介

本项目旨在构建一个算力平台答疑智能体，实现三层能力：

1. **基础层**：知识库 FAQ 检索 + 关键词意图识别 + 平台日志对接查询失败原因
2. **进阶层**：LLM 自然语言问答 + 日志自动诊断三类错误并给修复方案 + 主动推送预警
3. **高阶层**：多轮对话帮用户改写 sbatch 脚本 + 智能推荐最优分区/GPU/时长

## 技术栈

| 组件 | 技术选型 |
|------|----------|
| 开发语言 | Python 3.10+ |
| 后端框架 | FastAPI |
| 前端 | HTML + JS 单页应用 |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| 向量库 | ChromaDB |
| LLM | OpenAI 兼容格式（Qwen2.5-7B 首选） |
| 代码规范 | PEP 8 + ruff + mypy strict |
| 测试框架 | pytest |

## 快速开始

### 环境要求

- Python 3.10+
- pip

### 安装步骤

```bash
# 1. 克隆仓库
git clone <repo-url>
cd 107-agent

# 2. 创建虚拟环境
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# 3. 安装依赖
pip install -e ".[dev]"

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填写实际配置

# 5. 安装 pre-commit hooks
pre-commit install

# 6. 运行测试
pytest

# 7. 启动服务（开发模式）
python src/main.py
```

## 项目结构

```
107-agent/
├── src/                    # 源代码
│   ├── main.py             # FastAPI 入口
│   ├── config.py           # 配置管理
│   ├── knowledge/          # 知识库模块
│   ├── intent/             # 意图识别引擎
│   ├── log_analysis/       # 日志分析模块
│   ├── llm/                # LLM 集成
│   ├── monitor/            # 监控与推送
│   ├── dialog/             # 多轮对话管理
│   ├── script/             # sbatch 脚本处理
│   ├── recommender/        # 资源推荐引擎
│   ├── api/                # API 路由
│   └── frontend/           # 前端界面
├── tests/                  # 测试代码
├── docs/                   # 文档
├── scripts/                # 工具脚本
└── docker/                 # Docker 部署
```

## 开发规范

- 遵循 PEP 8，使用 ruff 自动检查
- 类型标注覆盖率 ≥ 90%（mypy strict 模式）
- 函数 ≤ 50 行，类 ≤ 300 行
- 所有函数/类/模块有 docstring
- commit message 格式：`[module] description`

详见 [CONTRIBUTING.md](CONTRIBUTING.md)

## 团队

| 角色 | 职责 | 工时 |
|------|------|------|
| A — 架构师/后端主力 | 整体架构、API 开发、核心引擎、LLM 管道 | 6h/天 |
| B — 知识工程/算法 | 知识库构建、意图引擎、日志分析、RAG 流程 | 6h/天 |
| D — 全栈/运维辅助 | 前端界面、测试编写、Docker 部署、文档维护 | 2h/天 |

## 许可证

MIT License
# Agent
