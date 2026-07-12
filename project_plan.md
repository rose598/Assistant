# 算力平台答疑智能体 — 项目规划书（详细版）

> 项目代号：107-Agent
> 团队成员：A（6h/天）、B（6h/天）、D（2h/天）
> 周总工时：3人 × 6天/周 → A/B 各 36h/周，D 12h/周，合计 **84h/周**
> （注：原 C 的工作已等分给 A 和 B，每人每天增加 2h）
> 总周期：6周（42天）| 总工时上限：约 504h
> 开发语言：Python 3.10+ | 后端框架：FastAPI | 前端：HTML+JS 单页应用
> 数据库：SQLite（开发）/ PostgreSQL（生产） | 向量库：ChromaDB
> 代码规范：PEP 8 + ruff + mypy strict | 测试框架：pytest

---

## 一、项目背景与目标

### 1.1 背景
USTC 本科生算力平台（107.ustc.edu.cn）基于 Slurm 调度系统，为全校本科生提供 GPU/CPU 共享计算资源。平台当前主要问题：

- **用户门槛高**：多数本科生首次接触 Linux / Slurm / 命令行，对 `sbatch`、`squeue`、`conda` 等概念陌生
- **报错信息不友好**：Slurm 原生错误如 `QOSMaxWallDurationPerJobLimit` 对新手几乎不可读
- **资源选择盲目**：用户不清楚该选哪个分区、申请多少 GPU、设多长运行时间
- **重复求助**：大量问题（conda 未激活、路径写错、GPU 没申请）在 FAQ 中有答案但用户找不到
- **缺乏主动服务**：排队拥堵只能在群里问，没有自动预警

现有官方文档（https://107.ustc.edu.cn/docs/）已覆盖 FAQ、Slurm 速查、资源说明等，但缺乏交互式排查工具。

### 1.2 目标
构建一个**算力平台答疑智能体**，实现以下三层能力：

1. **基础层**：知识库 FAQ 检索 + 关键词意图识别 + 平台日志对接查询失败原因
2. **进阶层**：LLM 自然语言问答 + 日志自动诊断三类错误并给修复方案 + 主动推送预警
3. **高阶层**：多轮对话帮用户改写 sbatch 脚本 + 智能推荐最优分区/GPU/时长

### 1.3 平台核心知识概要（从文档中提取）

| 类别 | 内容 | 来源 |
|------|------|------|
| **调度系统** | Slurm 作业调度系统，分区 Students/CPU-6530/GPU-RTX5090 | 平台概览 |
| **默认配额** | 4CPU / 1GPU / 4h（QOS: qos_stu_default） | 平台资源 |
| **QOS 层级** | default(4h) → small(8h) → medium_2gpu(12h) → long(72h) → cpu_long(72h) | 平台资源 |
| **常见报错** | QOSMaxWallDurationPerJobLimit, QOSMaxCpuPerUserLimit, CUDA OOM, Driver/library mismatch | FAQ + Slurm 速查 |
| **关键命令** | sbatch, squeue, scancel, scontrol show job, srun --pty, sinfo | Slurm 速查 |
| **作业状态** | PD(排队) / R(运行) / CG(收尾) / CD(完成) / F(失败) / CA(取消) | Slurm 速查 |
| **节点状态** | idle(空闲) / mix(部分占用) / comp(较满) / down(不可用) / drng(排空) | 分区输出 |
| **存储路径** | 用户目录 /home/scc/\<账号\>，共享存储需注意清理策略 | 平台资源 |

---

## 二、人员详细分工

### 2.1 角色定位矩阵

| 角色 | 能力画像 | 核心职责 | 覆盖模块 | 工时/周 |
|------|----------|----------|----------|---------|
| **A** 架构师/后端主力 | Python 高手，FastAPI、异步编程、系统设计、代码评审、LLM 集成 | 整体架构、API 开发、核心引擎、技术决策、LLM 管道 | 全模块（侧重后端+LLM 集成） | 36h |
| **B** 知识工程/算法 | NLP、数据爬取、知识库、正则规则、RAG、Prompt Engineering | 知识库构建、意图引擎、日志分析、RAG 流程、资源推荐 | 全模块（侧重数据+算法） | 36h |
| **D** 全栈/运维辅助 | 前后端、Docker、测试、文档编写 | 前端界面、测试编写、Docker 部署、文档维护 | 各模块辅助 + 文档 + 测试 + 部署 | 12h |

### 2.2 各成员详细职责

#### A — 架构师 / 后端主力（6h/天）

**核心技术栈**：Python, FastAPI, asyncio, LLM API, pytest, Git

**第1周（6h × 6天 = 36h）**：
- 搭建项目脚手架：目录结构、依赖管理（pyproject.toml）、配置文件模板
- 阅读平台全部文档，设计知识库 JSON Schema（意图分类、问答对、错误码映射的字段结构）
- 实现知识库加载器（从 JSON/YAML 读取，支持中文模糊匹配）
- 设计意图分类体系：4个一级类（作业提交、报错诊断、调度状态、权限资源），12个二级类
- 实现问答主流程：接收问题 → 意图识别 → 知识库检索 → 回复生成 的 pipeline
- 调研平台日志接口：分析 sacct / scontrol show job / squeue 的输出格式，设计解析方案
- 实现知识库 CLI 交互界面：支持单轮查询 / 交互式浏览两种模式
- 实现假数据模拟器：根据真实 scontrol/sacct 输出格式，生成模拟的作业日志数据，含各种错误场景

**第2周（6h × 6天 = 36h）**：
- 实现 SSH 客户端封装（asyncssh 异步 + 超时 30s + 重试 3 次 + 异常分类）
- 对接真实 sacct/scontrol 命令，实现用户最近任务查询
- 将失败原因映射到 FAQ 知识库条目，自动匹配解决方案
- 搭建 FastAPI 框架，配置 CORS、日志、异常处理
- 实现 Web API 三个核心端点：
  - `POST /api/ask`：接受自然语言问题，返回回复
  - `GET /api/jobs/{user}`：查询用户最近作业列表
  - `GET /api/jobs/{job_id}/diagnose`：分析作业失败原因
- 实现 /api/ask 和 /api/jobs 端点的具体业务逻辑
- 开发前端聊天界面（HTML+JS 单页，支持 Markdown 渲染、代码高亮）
- 前后端联调：ws 实时对话、错误回退、用户反馈收集

**第3周（6h × 6天 = 36h）**：
- LLM 选型评估：用 20 个平台相关问题对比 3 个模型的中文能力/延迟/价格
- 设计 RAG 全流程架构（Query → Retrieve → Augment → Generate）
- 设计 Prompt 模板体系：系统提示词 / RAG增强 / 脚本生成 / 日志分析 4 类模板
- 实现模糊提问理解模块：同义词扩展、停用词过滤、query 改写
- 集成基础匹配 + LLM 兜底的双通道问答策略，设计 fallback 机制
- 实现流式输出：SSE 协议，前端逐 token 显示
- 实现对话历史管理：Redis 存储 session，最近 10 轮，自动过期 1h
- A/B 测试框架：对比纯关键词匹配 vs LLM 增强的准确率、用户满意度

**第4周（6h × 6天 = 36h）**：
- 设计日志分类器整体架构（规则引擎 + LLM 双重判断）
- 实现 LLM 辅助日志分类：将原始日志文本送入 LLM 判断问题类别
- 实现规则 + LLM 双重判断：规则引擎先快速判断（毫秒级），低置信度时 fallback 到 LLM
- 实现一键修复命令生成：根据诊断结果生成可直接粘贴执行的命令
- 实现算力空闲检测模块：周期轮询 sinfo 输出，统计各分区空闲节点数
- 实现排队拥堵预警指标：排队作业数 > 20 或平均等待时间 > 30 分钟触发预警
- 实现空闲时段预测：基于 7 天滑动窗口的历史 sinfo 数据
- 实现推送通道：企业微信 Bot 通知、Email 通知、WebSocket 实时推送
- 实现定时调度器：APScheduler 每 10 分钟执行一次检测

**第5周（6h × 6天 = 36h）**：
- 设计多轮对话状态机：状态定义（INIT/IDENTIFY/COLLECT/CONFIRM/APPLY/DONE）、转换条件
- 实现对话状态存储：Redis 存储状态机上下文（当前状态/已收集字段/修改历史/回退栈）
- 实现 Slurm sbatch 脚本解析器：正则 + 有限状态机，提取 -J, -p, --qos, --gres, -c, --mem, -t 等字段
- 实现字段建议器：根据任务类型推荐 -p/--qos/--gres/-c/--mem/-t
- 实现对话式修改流程：状态驱引导用户逐步修改，每步收集一个参数
- 实现差分显示：difflib.unified_diff → HTML 高亮（绿色添加/红色删除）
- 实现一键复制 + 保存脚本（前端 Clipboard API + 后端生成 .sbatch 下载）
- 集成多轮对话到主流程，检测到"改脚本"意图时自动触发

**第6周（6h × 6天 = 36h）**：
- 设计资源推荐算法：任务类型 + 历史成功配置 + 当前集群状态
- 实现排队等待时间预测：k-NN 回归，特征 weekday+hour+partition+gpu+cpu+mem+time
- 实现运行时长推荐器：迭代数 × 单步时间 × 1.5 安全系数
- 实现 GPU 卡数推荐器：根据模型参数 + batch size + 训练数据量估算
- 全链路集成：将所有模块拼装，确保数据流畅通
- 全链路压力测试：locust 100 并发用户，混合场景持续 30 分钟
- 安全审计：SQL注入/XSS/API限流/敏感信息脱敏
- Docker 化部署（Dockerfile 多阶段构建 + docker-compose 编排）
- 最终验收测试

---

#### B — 数据处理 / 算法工程师（6h/天）

**核心技术栈**：Python, json, re, LLM API, ChromaDB, numpy, pandas, pytest

**第1周（6h × 6天 = 36h）**：
- 爬取/整理 Slurm 速查页面所有内容：28 个常用命令及参数、6 种作业状态码、12 个 SBATCH 字段说明
- 爬取平台资源页面：QOS 表格（7 种 QOS 的 CPU/GPU/内存/时间限制）、分区信息、节点状态说明
- 编写 FAQ JSON 条目（报错类、队列类、权限类），覆盖：
  - nvidia-smi 找不到 GPU / Driver/library version mismatch
  - 作业一直排队（5 种可能原因 + 对应建议）
  - QOSMaxWallDurationPerJobLimit / QOSMaxCpuPerUserLimit
  - 没有日志文件 / 日志为空 / 日志乱码
  - conda 安装 PyTorch 后是 CPU 版 / 作业里找不到 conda
  - CUDA out of memory / 系统 OOM / CPU workers 调优
  - VSCode 问题 / SSH 问题 / GitHub 连不上 / 上传压缩包异常
  - 求助时应该提供什么信息
- 实现关键词匹配引擎 v1：建立 200+ 关键词 → 意图的映射表，支持权重计算和阈值判断
- 编写意图匹配单测（20 个用例，含边界条件：多意图、无意图）
- 集成测试：10 个端到端查询场景，验证准确率和响应时间

**第2周（6h × 6天 = 36h）**：
- 实现基础日志解析器：从 scontrol show job 输出中提取 JobId, JobName, JobState, ExitCode, Partition, QOS, Command, WorkDir, Reason, NodeList
- 实现错误分类器：OOM / 脚本错误 / 环境缺失 / 权限限制 四大类，10 个子类
- 实现错误修复建议生成器：分类 → 匹配预定义模板 → 填充个性化信息（作业名、分区、路径等）
- 测试 10+ 种错误场景的分类准确率，输出混淆矩阵
- 准备进阶难度技术方案：对比 Qwen2.5-7B / DeepSeek-Chat / GLM4-9B-Chat 的中文能力/API延迟/价格/上下文长度/安全性
- 压力测试 + 代码审查 + 边缘 case 处理
- 编写验收测试文档

**第3周（6h × 6天 = 36h）**：
- 搭建 LLM API 客户端封装（OpenAI 兼容格式，含重试 3 次、超时 60s、token 统计）
- 实现向量化嵌入模块：BGE-small-zh-v1.5 模型封装，支持 batch 处理
- 构建向量数据库：知识库分块（chunk_size=256, overlap=32）→ 向量化 → 存入 ChromaDB
- 实现 RAG 流程：Query→Embed→Retrieve→Augment→Generate 全链路
- 实现 LLM 回答后处理：检测幻觉（关键词覆盖检查）、格式化（代码块/列表/表格）、来源标注
- 实现置信度评分：关键词匹配得分 × 0.4 + LLM 语义得分 × 0.6 加权融合
- 测试检索召回率（top-3 ≥ 90%, top-5 ≥ 95%）
- 优化 Prompt：根据测试结果调整系统提示词和 few-shot 示例
- 实现 LLM 调用缓存：MD5(query + prompt) → response，缓存 30 分钟，Redis 存储

**第4周（6h × 6天 = 36h）**：
- 收集真实/模拟日志样本：从平台历史作业收集或模拟生成，每类 20+ 条，共 60+ 条
- 实现规则引擎：通过正则表达式匹配三类错误的典型特征（30+ 条规则）
- 实现资源不足子类判定器：显存 OOM / 内存 OOM / 时间超限 / 磁盘空间不足
- 实现脚本错误子类判定器：语法错误 / 路径错误 / 依赖缺失 / 权限错误
- 实现环境缺失子类判定器：conda 未激活 / 包未安装 / CUDA 不匹配 / 内核问题
- 实现修复方案生成器：每种子类对应 1~3 条具体可执行的修复步骤
- 实现用户订阅管理：用户可订阅推送类型（排队预警/空闲提醒/作业完成）
- 端到端测试 + 文档更新

**第5周（6h × 6天 = 36h）**：
- 实现多轮上下文合并：将历史对话按角色（user/assistant）拼接，保留最近 N 轮 + 当前轮
- 实现脚本模板引擎：预设 5 个模板（最小 CPU 作业 / GPU 单卡训练 / GPU 多卡训练 / CPU 长任务 / 交互式调试）
- 实现 LLM 辅助脚本生成：用 LLM 将用户自然语言描述翻译成 sbatch 脚本
- 实现脚本验证器：检查：① 分区与 QOS 是否匹配 ② 资源是否超过 QOS 上限 ③ 语法是否合法 ④ -o/-e 目录是否存在
- 实现脚本执行测试：`sbatch --test-only` 模拟提交，返回验证结果
- 实现对话回退机制：用户说"回退/上一步/重来"时恢复上一个状态
- 测试脚本改写全流程（10 个复杂场景）+ 回退分支场景

**第6周（6h × 6天 = 36h）**：
- 实现历史作业分析模块：从 sacct 采集成功作业数据，统计各 QOS 平均排队时间/成功率
- 实现任务类型分类器：关键词匹配 + LLM 判断（深度学习/科学计算/数据分析/通用）
- 实现分区推荐器：对比所有可选分区，推荐预估排队最短的分区
- 实现综合推荐引擎：分区 + QOS + GPU + 时长 联合推荐，输出 top-3 排序列表
- 实现推荐理由生成器：自然语言解释推荐逻辑
- 测试推荐准确率（50 个历史作业回测 + 30 个用户场景）
- CI/CD 配置：GitHub Actions 自动化 → lint → test → build → deploy
- 最终演示准备 + 用户培训材料
- 项目总结合并、代码归档、知识库同步

---

#### D — 全栈 / 运维辅助（2h/天，12h/周）

**核心技术栈**：Python, HTML/CSS/JS, Docker, Git, Markdown

**第1周**：
- 搭建项目仓库：Git 初始化、.gitignore、README.md、commit 规范
- 初始化 Python 虚拟环境，锁定依赖版本
- 配置 ruff + mypy + pytest + pre-commit hooks
- 编写开发指南 README
- 整理平台常用错误码映射表（20+ 条）
- 编写基础使用文档 docs/usage.md

**第2周**：
- 编写 SSH 连接 mock 测试 + 连接异常测试
- 测试 10+ 种错误场景分类准确率，记录测试报告
- 编写 API 文档（OpenAPI 自动生成 + 手动补充示例）
- 编写部署文档 docs/deploy.md
- 编写基础功能演示视频脚本

**第3周**：
- 编写 LLM 调用测试（5 种典型问题）
- 测试检索召回率，编写测试报告
- 测试流式输出 + 对话管理
- 测试缓存命中率
- 文档更新

**第4周**：
- 标注样本数据：为每个日志分类子类标记 5~10 条样本
- 测试分类准确率 + 混淆矩阵输出
- 测试修复方案可行性（模拟执行 30 条修复命令）
- 测试监控 + 预测模块

**第5周**：
- 测试对话状态管理（新建/恢复/超时/异常中断 4 个场景）
- 测试脚本解析 + 生成（5 模板 × 3 参数组合 = 15 个用例）
- 测试脚本改写流程（完整流程 + 每步回退）
- 测试回退 + 分支场景

**第6周**：
- 收集历史作业数据样本（至少 200 条真实作业记录）
- 测试推荐准确率
- 修复压测 + 安全问题
- 部署测试（在 staging 环境完整跑通用户使用全流程）
- 项目总结合并、代码归档

---

### 2.3 协作与知识传递

| 模块 | 主负责人 | 协作方式 | 关键对接点 |
|------|----------|----------|-----------|
| 知识库 | B 负责内容，A 负责 schema | A 定义数据结构，B 填充条目，D 编写测试 | schema 定稿后 B 开始填充 |
| 意图引擎 | B | A 设计分类体系，B 实现匹配逻辑，D 测试 | A 输出分类文档后 B 编码 |
| 日志分析 | A + B 并行 | A 做 SSH 客户端 + API + LLM 分类，B 做规则引擎 + 子类判定器 | 共享 error_classifier 接口定义 |
| LLM 集成 | A + B 并行 | A 做选型+流式+对话管理，B 做 RAG+Embedding+Cache+Prompt | 共享 LLM client 实例 |
| 前端 | D 实现，A 联调 | D 写 HTML/CSS/JS，A 后端对接 + 联调 | API 先发布，D 按文档开发 |
| 脚本改写 | A 做状态机+解析+改写流程，B 做模板+验证+生成 | 状态机驱动对话，B 提供模板和 LLM 生成能力 | 共享 ScriptTemplate 定义 |
| 资源推荐 | B 主导算法，A 协助 | B 做分类器+推荐引擎，A 做排队预测+时长估算 | 共享 RecommenderOutput 结构 |
| 部署 | D 主导，A 协助 | D 写 Dockerfile + CI/CD，A 协助调试 | A 输出架构图后 D 开始 |

---

## 三、功能模块详细规格说明

### 3.1 知识库构建（基础 · 第1周）

**输入**：官方文档（FAQ / Slurm 速查 / 平台资源 / 提交任务 / 常见问题共 5 个页面）
**输出**：结构化的知识库 JSON 文件

**知识库 JSON Schema**：
```json
{
  "faq": [
    {
      "id": "faq-001",
      "category": "error_qos",
      "title": "提交作业时报 QOSMaxWallDurationPerJobLimit",
      "keywords": ["QOSMaxWallDurationPerJobLimit", "超时限制", "运行时间", "超过限制"],
      "intents": ["error_diagnosis", "job_submission"],
      "question": "为什么我提交作业时报 QOSMaxWallDurationPerJobLimit？",
      "answer": "这个错误表示作业申请的运行时间超过当前 QOS 允许的最长时间。\n\n**解决步骤**：\n1. 检查脚本中的 `#SBATCH -t` 或 GUI 中'最长运行时间'\n2. 如果使用默认 QOS（qos_stu_default），运行时间不超过 4 小时\n3. 长任务先跑短时间 smoke test，确认流程正确后再申请额外算力\n\n**参考**：默认 QOS 为 4h，需要更长时间请通过平台资源申请入口提升 QOS。",
      "related_errors": ["QOSMaxCpuPerUserLimit"],
      "references": ["Slurm速查 - 当前默认配置", "平台资源 - QOS与资源上限"]
    }
  ]
}
```

**需要覆盖的分类体系**：

| 一级类 | 二级类 | 条目数 | 示例关键词 |
|--------|--------|--------|-----------|
| error_diagnosis | qos_limit | 5+ | QOSMaxWall, QOSMaxCpu, QOSMaxGPU |
| error_diagnosis | gpu_related | 4+ | nvidia-smi, CUDA, Driver/library |
| error_diagnosis | oom | 3+ | out of memory, OOM, 显存不足 |
| error_diagnosis | script_error | 5+ | 语法错误, 路径错误, 文件不存在 |
| error_diagnosis | env_missing | 4+ | conda, module not found, ImportError |
| job_submission | interactive | 3+ | srun, --pty, 交互式 |
| job_submission | batch | 4+ | sbatch, 批处理, 脚本 |
| job_submission | cancel | 2+ | scancel, 取消任务 |
| job_status | queuing | 4+ | PD, 排队, 等待, pending |
| job_status | running | 3+ | R, running, 运行中 |
| job_status | failed | 3+ | F, failed, 失败, ExitCode |
| permission | quota | 3+ | 限额, 配额, 资源上限 |
| permission | partition | 3+ | 分区, partition, 权限不足 |

---

### 3.2 意图识别引擎（基础 · 第1-2周）

**架构**：

```
用户输入
    │
    ▼
┌─────────────────────────────┐
│  预处理                     │
│  ├─ 去除标点/多余空格       │
│  ├─ 分句（如果有多句）       │
│  └─ 提取主要问题句          │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│  关键词匹配（基础通道）       │
│  ├─ 关键词权重表（200+ 词）  │
│  ├─ 计算各意图综合得分       │
│  └─ 阈值判断（>0.6 命中）    │
└──────────┬──────────────────┘
           │ 命中?  → 直接返回
           │ 未命中?
           ▼
┌─────────────────────────────┐
│  LLM 分类（进阶兜底）         │
│  ├─ 将问题送入 LLM           │
│  ├─ LLM 输出意图标签         │
│  ├─ 置信度校准              │
│  └─ 得分 < 0.3 → 转人工     │
└──────────┬──────────────────┘
           ▼
        回复用户
```

**关键词匹配表（示例，共需要 200+ 条）**：

| 关键词 | 权重 | 映射意图 |
|--------|------|----------|
| QOSMaxWall | 1.0 | error_qos_time |
| 运行时间 | 0.6 | error_qos_time |
| 超时 | 0.7 | error_qos_time |
| 4小时 | 0.5 | error_qos_time |
| nvidia-smi | 0.9 | error_gpu |
| 看不到GPU | 0.8 | error_gpu |
| CUDA out of memory | 1.0 | error_oom |
| 排队 | 0.7 | status_queuing |
| 一直排队 | 0.8 | status_queuing |
| PD | 0.9 | status_queuing |
| sbatch | 0.8 | job_batch |
| 提交作业 | 0.7 | job_submission |
| conda | 0.7 | env_conda |
| 找不到模块 | 0.8 | env_missing |
| 权限 | 0.6 | permission |
| 限额 | 0.7 | permission_quota |

---

### 3.3 日志接口对接（基础 · 第2周）

**支持的命令与输出解析**：

| 命令 | 功能 | 解析字段 |
|------|------|----------|
| `sacct -j <job_id> --format=JobID,JobName,State,ExitCode,ReqMem,MaxRSS,NNodes,NTasks` | 作业历史 | JobID, State, ExitCode, ReqMem |
| `scontrol show job <job_id>` | 作业详情 | JobState, Reason, Partition, QOS, WorkDir, Command |
| `squeue -u <user> --format="%i %P %j %T %M %l %D %R"` | 当前排队 | JobID, Partition, JobName, State |
| `sinfo -o "%P %D %A %a %l"` | 分区状态 | Partition, Nodes, Available |
| `cat <err_file>` | 错误日志 | 原始错误文本 |
| `cat <out_file>` | 输出日志 | 原始输出文本 |

**失败原因自动提取流程**：

```
用户输入 "我的作业失败了"
    │
    ▼
1. 调用 sacct -u $USER -S $(date +%Y-%m-%d) → 获取当天失败作业列表
    │
    ▼
2. 对每个失败作业调用 scontrol show job <job_id> → 获取 Reason 字段
    │
    ▼
3. 读取作业的 .err 文件 → 获取详细的错误栈
    │
    ▼
4. 合并信息 → 调用错误分类器 → 匹配知识库 → 生成回复
```

---

### 3.4 LLM 接入（进阶 · 第3周）

**选型评估维度**：

| 模型 | 中文能力 | 上下文长度 | API 延迟 | 价格 | 结论 |
|------|----------|------------|----------|------|------|
| Qwen2.5-7B | ★★★★★ | 128K | 低 | 低 | ✅ **首选** |
| DeepSeek-Chat | ★★★★☆ | 32K | 中 | 中 | 备选 |
| GLM4-9B-Chat | ★★★★★ | 128K | 中 | 中 | 备选 |

**RAG 流程设计**：

```
用户问题
    │
    ▼
┌──────────────┐
│ Query 理解   │ (A 负责)
│ ├ 同义词扩展 │
│ ├ 停用词过滤 │
│ └ 意图识别   │
└──────┬───────┘
       ▼
┌──────────────┐
│ 知识库检索   │ (B 负责)
│ ├ 关键词匹配 │
│ ├ Embedding  │
│ └ 混合排序  │
└──────┬───────┘
       ▼  top-3 条目
┌──────────────┐
│ Augment      │ (B 负责)
│ ├ 注入 Prompt│
│ └ 组装上下文 │
└──────┬───────┘
       ▼
┌──────────────┐
│ LLM 生成     │ (A 负责)
│ ├ 调用 LLM   │
│ └ 流式返回   │
└──────┬───────┘
       ▼
┌──────────────┐
│ 后处理       │ (B 负责)
│ ├ 格式规范   │
│ ├ 来源标注   │
│ └ 置信度评分 │
└──────┬───────┘
       ▼
    最终回复
```

**Prompt 模板示例（B 负责设计）**：

```
你是中国科学技术大学 107 算力平台的智能助手。
你的职责是帮助本科生解答关于 Slurm 作业调度、GPU 使用、环境配置等问题。

## 知识参考
{retrieved_knowledge}

## 回答要求
1. 只回答与 107 算力平台相关的问题
2. 基于知识库回答，不要编造信息
3. 如果知识库没有相关信息，请说"这个问题我需要查一下平台文档"
4. 回答要简洁，使用中文，适当使用列表和代码块
5. 对于常见错误，给出具体的修复步骤和命令

## 用户问题
{user_question}
```

---

### 3.5 日志智能解析（进阶 · 第4周）

**三类错误与子类判定规则**：

| 大类 | 子类 | 判定规则（正则） | 典型修复 |
|------|------|-----------------|---------|
| 资源不足 | 显存 OOM | `CUDA out of memory` / `CUDA_ERROR_OUT_OF_MEMORY` | 减小 batch size 或模型规模 |
| 资源不足 | 内存 OOM | `Killed` + `oom-killer` / `MemoryError` | 减少 --mem 请求或数据加载并发 |
| 资源不足 | 时间超限 | `DUE TO TIME LIMIT` / `TIMEOUT` | 增加 -t 时间或使用 long QOS |
| 脚本错误 | 语法错误 | `SyntaxError` / `ParseError` / `Invalid sbatch` | 检查脚本语法 |
| 脚本错误 | 路径错误 | `No such file or directory` / `FileNotFoundError` | 检查 cd 路径和文件是否存在 |
| 脚本错误 | 依赖缺失 | `ModuleNotFoundError` / `ImportError` | pip install 或 conda install |
| 脚本错误 | 权限错误 | `Permission denied` / `PermissionError` | 检查文件权限 chmod |
| 环境缺失 | conda 未激活 | `conda: command not found` / `CommandNotFoundError` | 在脚本中添加 conda 初始化 |
| 环境缺失 | CUDA 版本 | `CUDA driver version is insufficient` | 检查 nvidia-smi 驱动版本 |
| 环境缺失 | 内核版本 | `Illegal instruction` / `GLIBCXX` | 检查 gcc/glibc 版本 |

**分工说明**：
- A 负责：LLM 辅助分类（规则未命中时 LLM 兜底）+ 一键修复命令生成 + 定时调度器
- B 负责：规则引擎（30+ 正则）+ 3 个子类判定器 + 修复方案生成器 + 推送通道

---

### 3.6 主动推送（进阶 · 第4周）

**推送规则优先级**：

| 事件 | 触发条件 | 推送方式 | 优先级 | 负责人 |
|------|----------|----------|--------|--------|
| 排队拥堵 | 排队总数 > 20 或 平均等待 > 30min | 企业微信 Bot + WebSocket | P0 | A |
| 空闲时段 | 空闲 GPU 节点占比 > 60% | 企业微信 Bot | P1 | A |
| 作业完成 | 用户作业从 R 变 CD/F | Email 通知 | P0 | A |
| 分区异常 | 分区 down/drng | 企业微信 Bot | P1 | A |

**定时调度配置**（A 负责）：
```python
SCHEDULER_CONFIG = {
    "queue_monitor": {"interval": "*/10 * * * *", "func": check_queue_congestion},
    "idle_detector": {"interval": "*/15 * * * *", "func": detect_idle_resources},
    "job_watcher": {"interval": "*/5 * * * *", "func": watch_user_jobs},
    "prediction": {"interval": "0 */1 * * *", "func": update_prediction_model},
}
```

---

### 3.7 多轮对话脚本改写（高阶 · 第5周）

**状态机定义**：

```
                    ┌──────────┐
                    │  INIT    │  ← 用户首次进入脚本改写模式
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │ IDENTIFY │  ← 确认用户想改什么（分区/GPU/时长/全改）
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │ COLLECT  │  ← 逐一收集新参数值
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │ CONFIRM  │  ← 展示新旧对比，请用户确认
                    └────┬─────┘
                    ┌────┴─────┐
                    ▼          ▼
               ┌────────┐ ┌────────┐
               │ APPLY  │ │ ROLLBACK│  ← 用户说"回到上一步"
               └────┬───┘ └────────┘
                    ▼
               ┌──────────┐
               │  DONE    │
               └──────────┘
```

**分工说明**：
- A 负责：状态机设计实现 + sbatch 脚本解析器 + 字段建议器 + 对话式修改流程 + 差分显示 + 一键导出 + 集成
- B 负责：上下文合并 + 脚本模板引擎 + LLM 辅助脚本生成 + 脚本验证器 + 脚本执行测试 + 回退机制

**脚本模板引擎预设模板（B 负责）**：

| 模板名 | 适用场景 | 默认参数 |
|--------|----------|----------|
| minimal_cpu | 简单 CPU 计算 | -p Students, -c 1, --mem 4G, -t 00:10:00 |
| gpu_single | 单卡 GPU 训练 | -p Students, --qos=qos_stu_default, --gres=gpu:1, -c 4, --mem 16G, -t 04:00:00 |
| gpu_multi | 多卡 GPU 训练 | -p Students, --qos=qos_stu_medium_2gpu, --gres=gpu:2, -c 8, --mem 32G, -t 12:00:00 |
| cpu_long | 长时间 CPU 计算 | -p Students, --qos=qos_stu_cpu_long, -c 8, --mem 32G, -t 72:00:00 |
| debug_interactive | 交互式调试 | srun -p Students --qos=qos_stu_default --gres=gpu:1 -c 1 -t 00:10:00 --pty bash |

---

### 3.8 智能资源推荐（高阶 · 第6周）

**推荐算法流程**：

```
用户描述："我要训练一个 ResNet50，数据量 10GB，batch_size=64"
    │
    ▼
┌─────────────────────┐
│ 任务类型分类         │  (B 负责)
│ ├ 深度学习 (0.95)   │
│ ├ 科学计算 (0.02)   │
│ ├ 数据分析 (0.02)   │
│ └ 通用 (0.01)       │
└─────────┬───────────┘
           ▼
┌─────────────────────┐
│ GPU 卡数推荐        │  (A 负责)
│ ├ 模型大小 = 98MB   │
│ ├ batch_size = 64   │
│ ├ 每卡显存需求 ≈ 6GB│
│ └ 推荐 1 张 GPU      │
└─────────┬───────────┘
           ▼
┌─────────────────────┐
│ 分区/QOS 推荐       │  (B 负责)
│ ├ qos_stu_default   │
│ │  排队时间 ≈ 2min  │
│ │  限制 4CPU/1GPU/4h│
│ └ ✅ 最推荐          │
└─────────┬───────────┘
           ▼
┌─────────────────────┐
│ 运行时长推荐        │  (A 负责)
│ ├ 估计迭代数 = 100   │
│ ├ 单步时间 ≈ 0.5s   │
│ ├ 总时长 ≈ 50min    │
│ └ 推荐 -t 01:00:00  │
└─────────┬───────────┘
           ▼
┌─────────────────────┐
│ 综合推荐输出         │  (B 负责整合)
│ ├ 分区: Students    │
│ ├ QOS: qos_stu_default│
│ ├ GPU: 1            │
│ ├ CPU: 4            │
│ ├ 内存: 16G         │
│ ├ 时长: 01:00:00    │
│ └ 预估排队: ~2min   │
└─────────────────────┘
```

**排队等待时间预测模型**（A 负责）：
- 输入特征：weekday（星期几）, hour（小时）, partition（分区）, gpu_count（GPU 数）, cpu_count（CPU 数）, memory（内存）, time_limit（时长）
- 输出：predicted_wait_time（预测等待时间，单位：秒）
- 算法：基于 7 天滑动窗口的 k-NN 回归（简单高效，可解释性强）
- 冷启动：无历史数据时，返回分区平均排队时间

---

## 四、项目目录结构

```
107-agent/
├── README.md
├── pyproject.toml                # 依赖 + 项目配置
├── .pre-commit-config.yaml       # pre-commit hooks
├── .github/workflows/
│   └── ci.yml                    # GitHub Actions CI/CD
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── .env.example
├── docs/
│   ├── usage.md                  # 使用指南
│   ├── deploy.md                 # 部署指南
│   ├── api.md                    # API 文档
│   └── contributing.md           # 贡献指南
├── src/
│   ├── __init__.py
│   ├── main.py                   # FastAPI 入口
│   ├── config.py                 # 配置管理
│   ├── knowledge/
│   │   ├── __init__.py
│   │   ├── loader.py             # 知识库加载器
│   │   ├── schema.py             # 知识库数据类型
│   │   ├── matcher.py            # 关键词匹配引擎
│   │   └── data/                 # 知识库 JSON 文件
│   │       ├── faq_errors.json
│   │       ├── faq_usage.json
│   │       ├── slurm_commands.json
│   │       ├── qos_table.json
│   │       └── error_codes.json
│   ├── intent/
│   │   ├── __init__.py
│   │   ├── classifier.py         # 意图分类器
│   │   ├── keywords.py           # 关键词→意图映射表
│   │   └── rules.py              # 规则模板
│   ├── log_analysis/
│   │   ├── __init__.py
│   │   ├── ssh_client.py         # SSH 连接封装 (A)
│   │   ├── job_query.py          # 作业查询接口 (A)
│   │   ├── log_parser.py         # 日志解析器 (B)
│   │   ├── error_classifier.py   # 错误分类器 (B)
│   │   ├── failure_analyzer.py   # 失败原因分析 (A)
│   │   └── fix_generator.py      # 修复方案生成 (B)
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py             # LLM API 客户端 (B)
│   │   ├── prompts.py            # Prompt 模板 (B)
│   │   ├── embedding.py          # 向量嵌入 (B)
│   │   ├── vector_store.py       # 向量数据库 (B)
│   │   ├── rag_engine.py         # RAG 引擎 (B)
│   │   ├── cache.py              # LLM 调用缓存 (B)
│   │   └── postprocess.py        # 回答后处理 (B)
│   ├── monitor/
│   │   ├── __init__.py
│   │   ├── queue_monitor.py      # 队列监控 (A)
│   │   ├── idle_detector.py      # 空闲检测 (A)
│   │   ├── prediction.py         # 空闲时段预测 (A)
│   │   ├── scheduler.py          # 定时调度器 (A)
│   │   └── notifier.py           # 推送通知 (A)
│   ├── dialog/
│   │   ├── __init__.py
│   │   ├── session.py            # 会话管理 (A)
│   │   ├── state_machine.py      # 对话状态机 (A)
│   │   ├── context.py            # 上下文管理 (B)
│   │   └── rollback.py           # 回退机制 (B)
│   ├── script/
│   │   ├── __init__.py
│   │   ├── parser.py             # sbatch 脚本解析器 (A)
│   │   ├── templates.py          # 脚本模板 (B)
│   │   ├── generator.py          # 脚本生成 (B)
│   │   ├── validator.py          # 脚本验证器 (B)
│   │   └── differ.py             # 脚本差异比较 (A)
│   ├── recommender/
│   │   ├── __init__.py
│   │   ├── task_classifier.py    # 任务类型分类 (B)
│   │   ├── partition_rank.py     # 分区排序 (B)
│   │   ├── gpu_estimator.py      # GPU 需求估算 (A)
│   │   ├── time_estimator.py     # 时长估算 (A)
│   │   ├── wait_time.py          # 排队预测 (A)
│   │   └── combined.py           # 综合推荐 (B)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes_ask.py         # 问答接口
│   │   ├── routes_jobs.py        # 作业查询接口
│   │   ├── routes_subscription.py# 订阅接口
│   │   ├── routes_feedback.py    # 反馈接口
│   │   └── websocket.py          # WebSocket
│   └── frontend/
│       ├── index.html            # 聊天界面
│       ├── styles.css            # 样式
│       └── scripts.js            # JS 逻辑
├── tests/
│   ├── conftest.py               # 测试配置
│   ├── test_knowledge/
│   ├── test_intent/
│   ├── test_log_analysis/
│   ├── test_llm/
│   ├── test_monitor/
│   ├── test_dialog/
│   ├── test_script/
│   ├── test_recommender/
│   └── test_api/
└── scripts/
    ├── seed_knowledge.py          # 初始化知识库
    ├── simulate_jobs.py           # 模拟作业数据
    └── benchmark.py               # 性能测试
```

---

## 五、技术选型与规格说明

| 组件 | 技术选型 | 版本 | 选型理由 | 负责人 |
|------|----------|------|----------|--------|
| 后端框架 | FastAPI | 0.110+ | 异步支持、自动OpenAPI文档、高性能 | A |
| Web 服务 | Uvicorn | 0.29+ | 与 FastAPI 原生配合 | A |
| SSH 客户端 | asyncssh | 2.16+ | 原生异步 SSH 支持 | A |
| 向量数据库 | ChromaDB | 0.5+ | 轻量、无需单独部署、支持中文 | B |
| Embedding | BAAI/bge-small-zh-v1.5 | - | 中文语义检索最佳小模型 | B |
| LLM API | OpenAI 兼容格式 | - | 统一接口，可切换多个模型 | A+B |
| 前端 | 原生 HTML+JS | - | 轻量、无框架依赖 | D |
| 会话存储 | Redis（可选）/ 内存 | - | 开发时用内存，生产用 Redis | A |
| 定时调度 | APScheduler | 3.10+ | 功能丰富、支持持久化 | A |
| 测试 | pytest | 8.0+ | 生态丰富 | D |
| 容器化 | Docker + docker-compose | - | 一键部署 | D |
| CI/CD | GitHub Actions | - | 免费、与 GitHub 集成 | D |

---

## 六、每日详细规划

### 第1周 — 知识库构建 + 基础框架

**本周目标**：搭建项目骨架，完成知识库建设（50+ FAQ 条目），实现知识库加载器和关键词匹配引擎 v1

| 日期 | 人员 | 任务描述 | 工时 | 产出物 | 验收标准 |
|------|------|---------|------|--------|----------|
| **周一** | A | 创建项目目录结构、pyproject.toml、配置文件模板、Git 初始化 | 4h | 可运行的项目骨架 | `pip install -e .` 无报错 |
| 周一 | A | 实现知识库 CLI 交互界面（单轮查询 + 交互式浏览） | 2h | `cli.py` | 可交互运行 |
| 周一 | B | 阅读官方 5 个文档页，提取所有 FAQ 问题，设计知识库 JSON Schema | 4h | 知识库 schema 文档 + 模板 JSON | schema 覆盖 4 大类意图 |
| 周一 | B | 爬取/整理 Slurm 速查 + 平台资源页面，提取命令、状态码、SBATCH 字段 | 2h | Slurm 知识条目 50+ | 每个条目含 id/title/keywords/answer |
| 周一 | D | 搭建 Python 虚拟环境，配置 ruff + mypy + pytest，编写 README | 2h | 项目开发环境 + 文档 | ruff 无错误，mypy strict 通过 |
| **周二** | A | 编写 FAQ 条目 30 条（报错类 15 + 队列类 8 + 权限类 7） | 4h | FAQ JSON（30条） | 每条包含 keywords + intents |
| 周二 | A | 实现知识库加载器：JSON → Python dict，支持中英文模糊匹配（fuzzywuzzy） | 2h | `knowledge/loader.py` | 加载 50+ 条目 ≤ 0.5s |
| 周二 | B | 编写 FAQ 条目 20 条（环境配置类 12 + 文件类 5 + 其他 3） | 4h | FAQ JSON（20条） | 覆盖 conda/CUDA/文件传输 |
| 周二 | B | 编写单测覆盖知识库查询（空查询/多关键词/特殊字符/超大文本） | 2h | `tests/test_knowledge/` | 全部通过 |
| 周二 | D | 配置 pre-commit hooks，编写开发指南 CONTRIBUTING.md | 2h | pre-commit 配置 + 文档 | 每次 commit 自动检查 |
| **周三** | A | 设计意图分类体系：4 个一级类、12 个二级类，编写分类文档 | 4h | 意图分类文档 | 覆盖所有 FAQ 条目 |
| 周三 | A | 实现问答主流程 Pipeline：问题 → 意图识别 → 知识库检索 → 回复生成 | 2h | `qa_engine.py` | 端到端平均响应 ≤ 1s |
| 周三 | B | 实现关键词匹配引擎 v1：200+ 关键词 → 意图映射表，权重 + 阈值判断 | 4h | `intent/matcher.py` | 准确率 ≥ 85%（20 个测试问题） |
| 周三 | B | 编写意图匹配单测（20 个用例，含边界条件：多意图、无意图） | 2h | `tests/test_intent/` | 全部通过 |
| 周三 | D | 整理平台常用错误码映射表（Slurm 错误码 + 系统错误码 + Python 异常） | 2h | `knowledge/data/error_codes.json` | 20+ 条映射 |
| **周四** | A | 调研平台日志 API：在平台执行 sacct/scontrol/squeue，记录输出格式 | 4h | API 调研文档 | 包含命令输出示例 |
| 周四 | A | 实现假数据模拟器：生成 20 条模拟作业日志（含 5 种错误类型） | 2h | `log_simulator.py` | 输出格式匹配真实 sacct |
| 周四 | B | 实现基础日志解析器：从 scontrol show job 输出中解析关键字段 | 4h | `log_parser.py` | 正确解析 10 个字段 |
| 周四 | B | 实现集成测试：10 个端到端查询场景，验证准确率和响应时间 | 2h | `tests/test_integration.py` | 全部通过 |
| 周四 | D | 编写基础使用文档 docs/usage.md（目录说明、如何新增FAQ、如何测试） | 2h | `docs/usage.md` | 覆盖主要开发操作 |
| **周五** | A | 实现问答主流程完整 Pipeline + CLI 界面 | 4h | `qa_engine.py` + `cli.py` | 端到端 ≤ 1s |
| 周五 | A | 检查点：集成知识库 + 意图识别 + 日志解析为 v0.1 原型 | 2h | v0.1 可运行原型 | 3 个端到端场景可用 |
| 周五 | B | 完善关键词映射表（补充剩余关键词，达到 200+） | 4h | `intent/keywords.py` | 200+ 映射 |
| 周五 | B | 编写日志解析测试（5 种格式变体） | 2h | 测试用例 | 全部通过 |
| 周五 | D | 编写日志解析测试补充 | 2h | 测试用例 | 覆盖边界 |
| **周六** | A | 集成测试 + Bug 修复（Checklist 20 项） | 4h | 修复记录 | 所有 blocker bug 关闭 |
| 周六 | A | 集成知识库 + 意图识别 + 日志解析为 v0.1 原型 | 2h | v0.1 可运行原型 | 3 个端到端场景可用 |
| 周六 | B | 编写验收测试（10 个典型用户问题场景） | 4h | 验收测试用例 | 场景覆盖率 100% |
| 周六 | B | 代码审查（A 审查 B 的代码，反之亦然） | 2h | 审查记录 | 20 项 check 全部过 |
| 周六 | D | 协助验收测试用例编写 | 2h | 验收测试补充 | 覆盖边界 case |

---

### 第2周 — 日志接口 + 基础完善

**本周目标**：对接真实平台日志接口，实现 Web API + 前端界面，完成基础难度验收

| 日期 | 人员 | 任务描述 | 工时 | 产出物 | 验收标准 |
|------|------|---------|------|--------|----------|
| **周一** | A | 实现 SSH 客户端封装（asyncssh 异步 + 超时 30s + 重试 3 次 + 异常分类） | 4h | `ssh_client.py` | 连接失败有明确错误提示 |
| 周一 | A | 实现用户最近任务查询（sacct -u $USER -S date → 解析最近 10 个作业） | 2h | `job_query.py` | 返回 JobID/State/ExitCode/Time |
| 周一 | B | 实现失败原因自动提取（合并 scontrol + .err 文件信息 → 结构化输出） | 4h | `failure_analyzer.py` | 输出含作业ID+状态+错误信息+建议 |
| 周一 | B | 实现失败原因 → FAQ 知识库映射器 | 2h | `fault_to_faq.py` | 匹配准确率 ≥ 90% |
| 周一 | D | 编写 SSH 连接测试（连接正常/超时/拒绝/认证失败） | 2h | 测试代码 | 4 种场景覆盖 |
| **周二** | A | 实现错误分类器 4 大类 + 10 子类（OOM/脚本错误/环境缺失/权限限制） | 4h | `error_classifier.py` | 分类准确率 ≥ 85% |
| 周二 | A | 实现错误修复建议生成器（分类→预定义模板→填充作业信息） | 2h | `fix_generator.py` | 每类至少 1 条可执行建议 |
| 周二 | B | 实现 /api/ask 端点（POST，接受 question 返回 answer + confidence + sources） | 4h | `routes_ask.py` | OpenAPI 文档自动生成 |
| 周二 | B | 实现 /api/jobs 端点（GET /{user} 查询 + GET /{user}/{job_id} 诊断） | 2h | `routes_jobs.py` | 返回结构化 JSON |
| 周二 | D | 测试 10+ 种错误场景分类准确率 | 2h | 测试报告（含混淆矩阵） | 准确率 ≥ 85% |
| **周三** | A | 搭建 FastAPI 框架（CORS/日志/middleware/异常处理/健康检查端点） | 4h | `api.py` | `/health` 返回 200 |
| 周三 | A | 编写前端聊天界面（HTML + CSS + JS，支持 Markdown + 代码高亮） | 2h | `frontend/index.html` | 基本交互可用 |
| 周三 | B | 实现前端聊天界面配套 JS（fetch/WebSocket 通信） | 4h | `frontend/scripts.js` | 前后端通信正常 |
| 周三 | B | 准备进阶难度技术方案：对比 3 个 LLM 模型 | 2h | 技术选型文档 | 输出推荐模型 |
| 周三 | D | 编写 API 文档（附 curl 示例 + Python 调用示例） | 2h | OpenAPI 文档 | 3 个端点都有示例 |
| **周四** | A | 前后端联调：/api/ask 前端调用 → 后端回复 → 前端渲染 | 4h | 联调测试 | 3 种类型的消息都显示正常 |
| 周四 | A | 用户反馈收集机制（"有用/无用"按钮 + SQLite 日志记录） | 2h | `feedback.py` | 反馈数据写入 SQLite |
| 周四 | B | 完善 /api/ask 和 /api/jobs 端点逻辑 | 4h | 完善端点 | 返回结构化 JSON |
| 周四 | B | 前后端联调 WebSocket 实时对话 | 2h | 联调测试 | 延迟 ≤ 1s |
| 周四 | D | 编写部署文档：Dockerfile + docker-compose.yml + 环境变量说明 | 2h | `docs/deploy.md` | 按文档可本地部署 |
| **周五** | A | 压力测试：100 并发请求 /api/ask，记录 P50/P95/P99 延迟 | 4h | 压测报告 | P99 ≤ 5s |
| 周五 | A | 边缘 case 处理（空输入/表情符号/纯标点/超长 5000 字/SQL注入尝试） | 2h | 修复列表 | 所有 case 有合理返回 |
| 周五 | B | 代码审查 + 重构（模块解耦、统一错误码、类型标注补齐） | 4h | 重构记录 | mypy strict 全部通过 |
| 周五 | B | LLM 选型评估：用 20 个平台相关问题对比 3 个模型 | 2h | 选型评估报告 | 明确最优推荐 |
| 周五 | D | 编写基础功能演示视频脚本（5 分钟，5 个典型场景） | 2h | 演示脚本 | 每个场景有预期结果 |
| **周六** | A | 集成测试 + Bug 修复 → 稳定版 v1.0 | 4h | 稳定版 v1.0 | 20 个回归测试全过 |
| 周六 | A | 输出基础难度验收报告 | 2h | 验收报告 | 基础难度 3 个模块全部完成 |
| 周六 | B | 输出基础难度验收报告（功能清单/测试结果/性能指标/遗留问题） | 4h | 验收报告 | 基础难度 3 个模块全部完成 |
| 周六 | B | 准备第3周技术预研（LLM 相关） | 2h | 技术预研笔记 | 明确第3周技术路线 |
| 周六 | D | 协助验收 + 文档最终检查 | 2h | 验收协助 | 文档无遗漏 |

---

### 第3周 — LLM 接入 + 自然语言问答

**本周目标**：完成 LLM 选型与接入，实现 RAG 增强问答、流式输出、对话管理

| 日期 | 人员 | 任务描述 | 工时 | 产出物 | 验收标准 |
|------|------|---------|------|--------|----------|
| **周一** | A | LLM 选型评估：用 20 个平台相关问题对比 3 个模型的中文能力/延迟/价格 | 4h | 选型评估报告 | 明确最优推荐 |
| 周一 | A | 设计 RAG 全流程架构（Query → Retrieve → Augment → Generate） | 2h | 架构设计文档 | 架构图 + 接口定义 |
| 周一 | B | 搭建 LLM API 客户端：OpenAI 兼容格式封装 + 重试(3次) + 超时(60s) + token统计 | 4h | `llm/client.py` | 连接失败有降级策略 |
| 周一 | B | 设计 Prompt 模板体系：系统提示词/RAG增强/脚本生成/日志分析 4 类模板 | 2h | `llm/prompts.py` | 每类有 2+ 版本可对比 |
| 周一 | D | LLM 调用测试：5 种典型问题（模糊/多意图/无效/长文本/代码问题） | 2h | 测试结果 | 记录每种问题的回答质量 |
| **周二** | A | 实现模糊提问理解：同义词扩展（GPU↔显卡）、停用词过滤、query 改写 | 4h | `query_understanding.py` | 改写后检索提升 ≥ 10% |
| 周二 | A | 实现流式输出：SSE 协议，前端逐 token 显示 | 2h | `streaming.py` | 首 token ≤ 500ms |
| 周二 | B | 实现向量化嵌入模块：BGE-small-zh-v1.5 封装，支持 batch 处理 | 4h | `llm/embedding.py` | 单条嵌入 ≤ 100ms |
| 周二 | B | 构建向量数据库：知识库分块(chunk_size=256, overlap=32) → 存入 ChromaDB | 2h | `llm/vector_store.py` | 存储 50+ 条目 |
| 周二 | D | 测试检索召回率：20 个测试 query，top-3 召回率 | 2h | 测试报告 | top-3 ≥ 90% |
| **周三** | A | 实现对话历史管理：Redis 存储 session，最近 10 轮，自动过期 1h | 4h | `dialog/session.py` | 多轮对话上下文正确 |
| 周三 | A | A/B 测试框架：配置对比纯关键词 vs LLM 增强的准确率 | 2h | A/B 测试配置 | 可切换/对比 |
| 周三 | B | 实现 LLM 回答后处理：检测幻觉、格式化、来源标注 | 4h | `llm/postprocess.py` | 幻觉率 ≤ 5% |
| 周三 | B | 实现置信度评分：关键词匹配得分 × 0.4 + LLM 语义得分 × 0.6 | 2h | `confidence.py` | 评分与人工相关性 ≥ 0.8 |
| 周三 | D | 编写 LLM 集成测试（5 个测试场景） | 2h | 测试代码 | 全部通过 |
| **周四** | A | 集成"关键词 + LLM 兜底"双通道问答：得分 > 0.8 直接回复，否则走 LLM | 4h | `integrated_qa.py` | LLM 调用减少 40% |
| 周四 | A | 实现 RAG 流程完整链路（与 B 配合联调） | 2h | `llm/rag_engine.py` | 端到端延迟 ≤ 3s |
| 周四 | B | 实现 RAG 流程：Query→Embed→Retrieve→Augment→Generate 全链路 | 4h | `llm/rag_engine.py` | 端到端延迟 ≤ 3s |
| 周四 | B | 测试流式输出 + 对话管理（10 个多轮对话场景） | 2h | 测试报告 | 全部通过 |
| 周四 | D | 测试流式输出 + 对话管理 | 2h | 测试报告 | 参数验证 |
| **周五** | A | A/B 测试：纯关键词 vs LLM 增强，对比准确率 + 用户满意度（20 人 × 10 题） | 4h | A/B 测试报告 | LLM 方案准确率高 ≥ 15% |
| 周五 | A | 优化 Prompt：根据 A/B 测试结果调整系统提示词、few-shot 示例 | 2h | v2 prompt | 回答质量提升 ≥ 10% |
| 周五 | B | 实现 LLM 调用缓存：MD5(query + prompt) → response，缓存 30 分钟 | 4h | `llm/cache.py` | 缓存命中率 ≥ 20% |
| 周五 | B | 优化 Prompt：根据测试结果迭代提示词 | 2h | v2 prompt | 回答质量提升 ≥ 10% |
| 周五 | D | 测试缓存命中率（20 个常见问题 × 2 次） | 2h | 测试报告 | 命中率符合预期 |
| **周六** | A | 集成测试：50+ 个自然语言问题（含模糊提问/口语化/错别字） | 4h | 测试报告 | 正确率 ≥ 85% |
| 周六 | A | Bug 修复 + 性能优化（异步优化、连接池、批处理） | 2h | 修复记录 | 性能提升 ≥ 20% |
| 周六 | B | 集成测试：50+ 个自然语言问题 | 4h | 测试报告 | 正确率 ≥ 85% |
| 周六 | B | 文档更新：LLM 问答使用说明、FAQ 新增指南 | 2h | 文档 | 覆盖 LLM 配置说明 |
| 周六 | D | 文档检查 + 整合 | 2h | 最终文档 | 格式统一无遗漏 |

---

### 第4周 — 日志智能解析 + 主动推送

**本周目标**：实现日志的规则+LLM 双重解析、三类错误自动诊断、算力空闲/排队预警推送

| 日期 | 人员 | 任务描述 | 工时 | 产出物 | 验收标准 |
|------|------|---------|------|--------|----------|
| **周一** | A | 设计日志解析分类器架构（规则引擎 + LLM 双重判断，规则优先） | 4h | 分类器设计文档 | 架构图 + 接口定义 |
| 周一 | A | 实现 LLM 辅助分类：规则未命中时，将日志送入 LLM 判断类别 | 2h | `llm_log_classifier.py` | 规则+LLM 总覆盖率 ≥ 98% |
| 周一 | B | 收集日志样本：从平台历史记录/模拟器生成 60+ 条日志（每类 20+） | 4h | 日志样本库 | 含错误栈和上下文 |
| 周一 | B | 实现规则引擎：正则匹配三类错误特征（30+ 条正则规则） | 2h | `log_rule_engine.py` | 规则覆盖率 ≥ 90% |
| 周一 | D | 标注样本数据：为 60+ 条日志标注分类标签（子类级别） | 2h | 标注数据集 | 全部标注完成 |
| **周二** | A | 实现算力空闲检测：轮询 sinfo 输出，统计各分区 idle/mix/comp 节点数 | 4h | `idle_detector.py` | 检测周期 ≤ 30s |
| 周二 | A | 实现空闲时段预测：7 天滑动窗口历史数据，预测未来 4 小时空闲趋势 | 2h | `prediction.py` | 预测准确率 ≥ 70% |
| 周二 | B | 实现资源不足子类判定器：显存OOM/内存OOM/时间超限/磁盘空间 | 4h | `resource_analyzer.py` | 子类分类准确率 ≥ 90% |
| 周二 | B | 实现脚本错误子类判定器：语法错误/路径错误/依赖缺失/权限错误 | 2h | `script_error_analyzer.py` | 子类分类准确率 ≥ 90% |
| 周二 | D | 测试分类准确率（60+ 样本，输出混淆矩阵） | 2h | 测试报告 | 宏平均 F1 ≥ 0.85 |
| **周三** | A | 实现排队拥堵预警：squeue 统计排队总数 + 平均等待时间 + 按分区统计 | 4h | `queue_monitor.py` | 排队数/时间准确 |
| 周三 | A | 实现推送通道：企业微信 Bot / Email / WebSocket 3 种通道 | 2h | `monitor/notifier.py` | 3 种通道都可送达 |
| 周三 | B | 实现环境缺失子类判定器：conda未激活/包未安装/CUDA不匹配/内核问题 | 4h | `env_analyzer.py` | 子类分类准确率 ≥ 90% |
| 周三 | B | 实现修复方案生成器：子类 → 预定义修复模板 → 填充用户信息 | 2h | `fix_generator.py` | 每子类 1~3 条建议 |
| 周三 | D | 测试修复方案可行性（模拟执行 30 条修复命令） | 2h | 测试报告 | 成功率 ≥ 95% |
| **周四** | A | 实现定时调度器：APScheduler 每 10min 检测，每 1h 预测，触发即推送 | 4h | `monitor/scheduler.py` | 调度时间误差 ≤ 5s |
| 周四 | A | 实现一键修复命令生成：诊断 → 生成可直接粘贴执行的 pip/conda/sbatch 命令 | 2h | `auto_fix_cmd.py` | 命令语法正确可执行 |
| 周四 | B | 实现用户订阅管理：用户订阅推送类型（排队预警/空闲提醒/作业完成） | 4h | `subscription.py` | CRUD 完整 |
| 周四 | B | 测试监控 + 预测模块（10 个时段样本对比） | 2h | 测试报告 | 检测无遗漏 |
| 周四 | D | 测试监控 + 预测模块补充 | 2h | 测试报告 | 边界覆盖 |
| **周五** | A | 集成：日志解析 → 修复建议 → 推送 全流程联调 | 4h | v2.0 集成 | 10 个场景端到端通过 |
| 周五 | A | 端到端测试：10 个完整场景（提问→分析→诊断→修复→推送） | 2h | 测试报告 | 场景覆盖率 100% |
| 周五 | B | 实现规则 + LLM 双重判断完整链路测试 | 4h | 测试报告 | 规则+LLM 覆盖率 ≥ 98% |
| 周五 | B | 完善文档（推送配置说明、订阅管理说明） | 2h | 文档更新 | 覆盖推送功能 |
| 周五 | D | 测试推送功能（3 种通道各测试 3 次） | 2h | 测试报告 | 送达率 100% |
| **周六** | A | 稳定版 v2.0 集成：全部 Bug 修复 | 4h | 稳定版 v2.0 | 全部 bug 关闭 |
| 周六 | A | 文档更新 + 进阶难度验收报告 | 2h | 验收报告 | 进阶难度全部完成 |
| 周六 | B | 端到端测试补充：10 个完整场景 | 4h | 测试报告 | 场景覆盖率 100% |
| 周六 | B | 准备第5周技术预研（多轮对话 + 脚本改写相关） | 2h | 技术预研笔记 | 明确技术方案 |
| 周六 | D | 文档统一检查 + 格式规范 | 2h | 文档 | 格式统一 |

---

### 第5周 — 多轮对话 + 脚本改写

**本周目标**：实现多轮对话状态机、Slurm sbatch 脚本解析与生成、对话式修改流程

| 日期 | 人员 | 任务描述 | 工时 | 产出物 | 验收标准 |
|------|------|---------|------|--------|----------|
| **周一** | A | 设计对话状态机：5 个状态（INIT→IDENTIFY→COLLECT→CONFIRM→DONE）+ 转换条件 | 4h | 状态机设计文档 | 状态图 + 状态转换表 |
| 周一 | A | 实现对话状态存储：Redis 存储 session 上下文（状态/收集字段/修改历史/回退栈） | 2h | `dialog/session.py` | 支持 1h 会话保持 |
| 周一 | B | 实现多轮上下文合并：user/assistant 交替拼接，保留最近 N 轮，token 超限截断 | 4h | `dialog/context.py` | 上下文正确拼接 |
| 周一 | B | 实现脚本模板引擎：5 个预设模板（minimal_cpu/gpu_single/gpu_multi/cpu_long/debug） | 2h | `script/templates.py` | 模板参数化可配置 |
| 周一 | D | 测试对话状态管理（新建/恢复/超时/异常中断 4 个场景） | 2h | 测试报告 | 全部通过 |
| **周二** | A | 实现 sbatch 脚本解析器：正则提取 -J, -p, --qos, --gres, -c, --mem, -t, -o, -e 字段 | 4h | `script/parser.py` | 正确解析 10+ 种写法 |
| 周二 | A | 实现字段建议器：根据任务类型 → 推荐 -p/--qos/--gres/-c/--mem/-t | 2h | `field_suggester.py` | 推荐合理可用 |
| 周二 | B | 实现 LLM 辅助脚本生成：自然语言→LLM→sbatch 脚本，配合模板后处理 | 4h | `script/generator.py` | 生成的脚本语法正确 |
| 周二 | B | 实现脚本验证器：检查分区↔QOS 匹配 / 资源≤上限 / 语法 / 输出目录存在 | 2h | `script/validator.py` | 检测出 5 类常见错误 |
| 周二 | D | 测试脚本解析 + 生成（5 模板 × 3 参数组合 = 15 用例） | 2h | 测试报告 | 全部通过 |
| **周三** | A | 实现对话式修改流程：状态驱引导用户逐步修改，每步收集一个参数 | 4h | `dialog/flow.py` | 完整流程可走通 |
| 周三 | A | 实现差分显示：difflib.unified_diff → HTML 高亮（绿色添加/红色删除） | 2h | `script/differ.py` | 对比结果清晰 |
| 周三 | B | 实现对话回退机制：用户说"回退/上一步/重来"时恢复上一个状态 | 4h | `dialog/rollback.py` | 支持多级回退 |
| 周三 | B | 实现脚本执行测试：`sbatch --test-only` 模拟提交，返回验证结果 | 2h | `script_test.py` | 验证结果含提示 |
| 周三 | D | 测试脚本改写流程（5 种完整流程 + 每步回退） | 2h | 测试报告 | 全部通过 |
| **周四** | A | 实现一键复制 + 保存脚本（前端 Clipboard API + 后端 .sbatch 下载） | 4h | `script_export.py` | 复制/保存都可用 |
| 周四 | A | 集成多轮对话到主流程：检测到"改脚本"意图 → 触发脚本改写子流程 | 2h | v3.0 集成 | 意图触发正确 |
| 周四 | B | 集成脚本改写：多轮对话中检测到脚本修改意图时自动切换状态 | 4h | `intent_to_script.py` | 切换无感知 |
| 周四 | B | 测试回退 + 分支场景（回退3步/回退到INIT/修改后回退） | 2h | 测试报告 | 全部通过 |
| 周四 | D | 测试脚本改写全流程（10 个复杂场景） | 2h | 测试报告 | 全部通过 |
| **周五** | A | 端到端多轮对话测试：10 个复杂场景（含修改参数/换分区/加GPU/改时长） | 4h | 测试报告 | 场景通过率 100% |
| 周五 | A | Bug 修复 + 体验优化（响应速度/错误提示/参数校验提示） | 2h | 修复记录 | 用户体验评分 ≥ 4/5 |
| 周五 | B | 完善脚本改写流程 + 端到端测试 | 4h | 测试报告 | 场景通过率 100% |
| 周五 | B | 用户使用指南更新：多轮对话使用说明、脚本改写示例 | 2h | 文档 | 含图文示例 |
| 周五 | D | 测试回退 + 分支场景 | 2h | 测试报告 | 全部通过 |
| **周六** | A | 稳定版 v3.0：全部集成 + Bug 修复 | 4h | v3.0 集成 | 全部 bug 关闭 |
| 周六 | A | 准备第6周技术预研（资源推荐算法相关） | 2h | 技术预研笔记 | 明确算法方案 |
| 周六 | B | 端到端多轮对话测试补充 + 文档审校 | 4h | 测试报告 + 文档 | 全部通过 |
| 周六 | B | 准备第6周技术预研（历史数据采集方案） | 2h | 数据采集方案 | 明确数据格式 |
| 周六 | D | 文档统一检查 + 用户指南整合 | 2h | 最终文档 | 格式统一 |

---

### 第6周 — 智能资源推荐 + 集成测试 + 部署

**本周目标**：实现智能资源推荐引擎，全链路集成，Docker 部署，最终验收

| 日期 | 人员 | 任务描述 | 工时 | 产出物 | 验收标准 |
|------|------|---------|------|--------|----------|
| **周一** | A | 设计资源推荐算法：任务类型 + 历史配置 + 当前集群状态 三因素加权 | 4h | 推荐算法设计文档 | 公式 + 伪代码完整 |
| 周一 | A | 实现排队时间预测：k-NN 回归，特征 weekday+hour+partition+gpu+cpu+mem+time | 2h | `wait_time_predictor.py` | 预测误差 ≤ 30% |
| 周一 | B | 实现任务类型分类器：关键词匹配 + LLM 判断（深度学习/科学计算/数据分析/通用） | 4h | `task_classifier.py` | 分类准确率 ≥ 90% |
| 周一 | B | 实现历史作业分析：从 sacct 采集成功作业 → 统计各配置的排队时间/成功率 | 2h | `history_analyzer.py` | 统计分析报表 |
| 周一 | D | 收集历史数据：从平台导出 200+ 条真实作业记录（含成功/失败） | 2h | 数据样本（CSV） | 字段完整可用 |
| **周二** | A | 实现运行时长推荐器：迭代数 × 单步时间 × 1.5 安全系数 | 4h | `time_estimator.py` | 推荐时长 ≥ 实际需要 |
| 周二 | A | 实现 GPU 卡数推荐器：根据模型参数 + batch size + 训练数据量估算 | 2h | `gpu_estimator.py` | 推荐的卡数不超需 |
| 周二 | B | 实现分区推荐器：对比所有可选分区，推荐预估排队最短的分区 | 4h | `partition_recommender.py` | 推荐分区排队最短 |
| 周二 | B | 实现综合推荐引擎：分区 + QOS + GPU + 时长 联合推荐，输出 top-3 | 2h | `combined_recommender.py` | 返回 top-3 推荐方案 |
| 周二 | D | 测试推荐准确率（50 个历史作业回测） | 2h | 测试报告 | 推荐配置成功率 ≥ 80% |
| **周三** | A | 全链路压力测试：locust 100 并发用户，混合场景持续 30 分钟 | 4h | 压测报告 | P95 ≤ 3s, 无500错误 |
| 周三 | A | 安全审计：SQL注入/XSS/API限流(100req/min)/敏感信息脱敏(账号路径隐藏) | 2h | 安全报告 | 高危漏洞 0 个 |
| 周三 | B | 实现推荐理由生成器：自然语言解释推荐逻辑 | 4h | `explanation_gen.py` | 理由合理可理解 |
| 周三 | B | 测试推荐系统（30 个用户场景，覆盖 4 类任务） | 2h | 测试报告 | 推荐满意度 ≥ 80% |
| 周三 | D | 修复压测 + 安全问题 | 2h | 修复记录 | 全部关闭 |
| **周四** | A | 全链路集成：知识库 + 意图 + 日志 + LLM + 推送 + 脚本改写 + 推荐 联调 | 4h | v4.0 全量集成 | 完整流程可走通 |
| 周四 | A | Docker 化部署：Dockerfile（多阶段构建：基础镜像→依赖→代码→启动） | 2h | Docker 部署包 | 构建成功 ≤ 10min |
| 周四 | B | 全链路集成配合 + 联调测试 | 4h | v4.0 全量集成 | 完整流程可走通 |
| 周四 | B | CI/CD 配置：GitHub Actions（push → lint → test → build → deploy） | 2h | CI/CD 配置 | 全流程自动化 |
| 周四 | D | 修复压测 + 安全问题 | 2h | 修复记录 | 全部关闭 |
| **周五** | A | 最终验收测试：基础(10例) + 进阶(10例) + 高阶(10例) 全部用例通过 | 4h | 验收测试报告 | 通过率 100% |
| 周五 | A | 最终演示准备：PPT + 演示视频（5 分钟） | 2h | 演示材料 | 可以交付 |
| 周五 | B | 部署文档 + 运维手册：环境变量表/健康检查/日志采集/备份/回滚 | 4h | 运维文档 | 覆盖部署全步骤 |
| 周五 | B | 用户培训材料编写 | 2h | 培训材料 | 覆盖全部功能 |
| 周五 | D | 部署测试：staging 环境完整跑通用户使用全流程 | 2h | 部署验证 | 全流程可用 |
| **周六** | A | 最终验收测试补充 + 演示材料定稿 | 4h | 验收测试报告 | 通过率 100% |
| 周六 | A | 项目总结合并：代码归档、知识库同步、文档最终版 | 2h | 项目归档 | 所有代码已 merge |
| 周六 | B | 最终验收测试 + 演示彩排 | 4h | 验收测试报告 | 通过率 100% |
| 周六 | B | 项目总结合并：CHANGELOG、代码归档 | 2h | 项目归档 | 所有代码已 merge |
| 周六 | D | 最终演示支持 + 培训材料印刷 | 2h | 演示材料 | 可以交付 |

---

## 七、代码规范与质量要求

### 7.1 Python 代码规范
- 遵循 PEP 8，使用 ruff 自动检查
- 类型标注覆盖率 ≥ 90%（mypy strict 模式通过）
- 函数 ≤ 50 行，类 ≤ 300 行
- 所有函数/类/模块有 docstring（中文，说明输入/输出/异常）
- 不允许 `except: pass`，必须指定异常类型
- 不允许硬编码路径/密码/URL，统一使用 config 管理

### 7.2 测试要求
- 单元测试覆盖率 ≥ 80%
- 每个模块有独立的测试目录
- 每个 API 端点有集成测试
- 测试数据使用 fixture 或 factory，不依赖外部服务
- 压测前使用 mock 避免影响真实平台

### 7.3 Git 规范
- commit message 格式：`[module] description`（如 `[knowledge] add faq loader`）
- 每个功能点一个 commit，不混杂
- main 分支保持可部署状态
- feature 分支命名：`feat/<module>-<description>`
- 每天结束时 push 当日代码

---

## 八、扩展性设计

### 8.1 知识库可扩展
- 新增 FAQ 只需在 JSON 文件中添加条目，无需改代码
- 支持热加载（不需重启服务）

### 8.2 平台适配可扩展
- 平台命令/参数/限制全部配置化（config.py）
- 切换不同 HPC 平台只需修改配置和少量适配层

### 8.3 LLM 可替换
- 所有 LLM 调用通过统一接口，切换模型只需改配置
- 支持 OpenAI 兼容格式的任意模型

### 8.4 前端可替换
- 后端提供纯 REST API + WebSocket，前端可完全替换
- 支持对接企业微信 / QQ 机器人

---

## 九、交付物清单

| 编号 | 交付物 | 说明 | 验收标准 | 负责人 |
|------|--------|------|----------|--------|
| D01 | 知识库 JSON 文件 | 覆盖 50+ FAQs，含分类/关键词/回答/引用 | 4 类意图，12 子类 | B |
| D02 | 关键词匹配引擎 | 200+ 映射，权重+阈值 | 准确率 ≥ 85% | B |
| D03 | SSH 日志客户端 | 异步，超时/重试/异常处理 | 3 种异常有提示 | A |
| D04 | 作业查询 API | 用户最近任务 + 失败诊断 | 字段完整，≤ 3s | A |
| D05 | LLM 问答系统 | RAG + 流式 + 多轮对话 | 正确率 ≥ 85% | A+B |
| D06 | 日志智能解析 | 3 类 10 子类自动诊断 + 修复方案 | F1 ≥ 0.85 | A+B |
| D07 | 主动推送 | 空闲预警 + 排队拥堵 + 3 通道 | 送达率 100% | A |
| D08 | 脚本改写系统 | 多轮对话式修改 sbatch | 10 个场景通过 | A+B |
| D09 | 资源推荐引擎 | 分区/GPU/时长推荐 + 排队预测 | 成功率 ≥ 80% | A+B |
| D10 | Web 聊天界面 | 前端 + FastAPI 后端 | 基本交互可用 | A+D |
| D11 | Docker 部署包 | Dockerfile + docker-compose | 一键部署 | D |
| D12 | 文档集 | 使用指南/部署手册/API 文档 | 覆盖全部操作 | D |
| D13 | 验收报告 | 测试报告 + 演示视频 | 全部用例通过 | A |

---

## 十、里程碑与甘特图概要

| 里程碑 | 时间 | 内容 | 依赖 | 验收人 |
|--------|------|------|------|--------|
| M1 | 第 2 周周末 | 基础难度完成 | 知识库 + 意图 + 日志查询可运行 | A+B+D |
| M2 | 第 4 周周末 | 进阶难度完成 | LLM 问答 + 日志诊断 + 推送可运行 | A+B+D |
| M3 | 第 6 周周末 | 高阶难度完成 | 多轮对话 + 脚本改写 + 推荐可运行 | A+B+D |
| M4 | 第 6 周周末 | 全量交付 | 集成测试通过 + 部署完成 + 文档完整 | 全员 |

```
第1周  ████████████████░░░░░░░░░░░░░░░░  M1: 知识库+意图+日志
第2周  ░░░░████████████████░░░░░░░░░░░░  M1: 集成+Web+验收
第3周  ░░░░░░░░████████████████░░░░░░░░  M2: LLM+RAG+流式
第4周  ░░░░░░░░░░░░████████████████░░░░  M2: 日志诊断+推送
第5周  ░░░░░░░░░░░░░░░░████████████████  M3: 多轮对话+脚本
第6周  ░░░░░░░░░░░░░░░░░░░░████████████  M3-M4: 推荐+集成+部署
```

---

## 十一、风险登记册

| 编号 | 风险 | 概率 | 影响 | 等级 | 应对措施 | 负责人 |
|------|------|------|------|------|----------|--------|
| R01 | 平台 API 不稳定/缺文档 | 中 | 高 | 🔴 | 模拟数据先行，保持 SSH fallback | A |
| R02 | LLM API 延迟高/不稳定 | 中 | 中 | 🟡 | 流式输出+缓存+基础关键词兜底 | A+B |
| R03 | 日志格式随平台升级变化 | 低 | 中 | 🟡 | 正则+LLM双重解析，配置化适配 | B |
| R04 | 团队成员请假/任务冲突 | 中 | 中 | 🟡 | A/B 互相 Backup，每周有缓冲 | A |
| R05 | 知识库与平台实际不一致 | 高 | 中 | 🟡 | 标注"动态事实"提示，提供手动更新接口 | B |
| R06 | 平台 SSH 访问受限 | 低 | 高 | 🔴 | 提供离线模式（仅知识库问答） | A |
| R07 | A/B 任务量过重（6h/天） | 中 | 中 | 🟡 | 严格按优先级执行，非核心降级 | A |
| R08 | 向量检索冷启动效果差 | 中 | 低 | 🟢 | 先用关键词匹配，边用边积累 | B |