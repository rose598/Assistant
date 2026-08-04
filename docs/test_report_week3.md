# 第3周测试报告 — LLM 接入与自然语言问答

> 角色 D | 周目标：LLM 调用、检索召回率、流式输出、对话管理、缓存命中率的测试与验收

项目规划第 3 周由角色 A、B 实现 LLM 相关模块，角色 D 负责测试与验收。
由于 A、B 的 `src/llm/`、`src/dialog/` 代码尚未落地（仓库中目前仅有空 `__init__.py`），
角色 D 遵循既有测试惯例，使用**自包含的 Mock/stub** 完成测试，待 A、B 实现后替换为真实导入即可复用整套用例。

---

## 一、本周交付物清单

| # | 交付物 | 文件 | 验收标准 |
|---|--------|------|----------|
| 1 | LLM 调用测试（5 种典型问题） | [test_llm_call.py](../tests/test_llm/test_llm_call.py) | 模糊/多意图/无效/长文本/代码问题均有正确回答 |
| 2 | 检索召回率测试 | [test_retrieval_recall.py](../tests/test_llm/test_retrieval_recall.py) | top-3 ≥ 90%，top-5 ≥ 95% |
| 3 | 流式输出测试（SSE 逐 token） | [test_streaming.py](../tests/test_llm/test_streaming.py) | 首 token ≤ 500ms，token 无丢失 |
| 4 | 对话管理测试 | [test_dialog_management.py](../tests/test_llm/test_dialog_management.py) | 多轮 ≤ 10 轮裁剪、过期 1h、中断恢复 |
| 5 | 缓存命中率测试 | [test_cache_hit_rate.py](../tests/test_llm/test_cache_hit_rate.py) | 20 问题 × 2 次命中率 ≥ 20% |
| 6 | 测试报告文档 | [test_report_week3.md](test_report_week3.md)（本文件） | 覆盖上述各项 |

---

## 二、测试运行结果

执行命令：

```bash
.venv\Scripts\python -m pytest tests/test_llm/ -v
```

**结果：`70 passed`，全部通过。**

```
collected 70 items
tests\test_llm\test_cache_hit_rate.py ...........        [ 15%]
tests\test_llm\test_dialog_management.py .............   [ 34%]
tests\test_llm\test_llm_call.py .....                    [ 41%]
tests\test_llm\test_retrieval_recall.py ................. [ 88%]
tests\test_llm\test_streaming.py ........                [100%]
```

质量门禁（ruff + mypy strict）同样通过：

```bash
# ruff 代码规范
.venv\Scripts\python -m ruff check tests/test_llm/   # All checks passed!
# mypy 严格类型检查
.venv\Scripts\python -m mypy tests/test_llm/         # Success: no issues found
```

---

## 三、各模块详解

### 3.1 LLM 调用测试（test_llm_call.py，5 个用例）

覆盖计划要求的 5 种典型问题类型：

| 类型 | 用例 | 验收要点 |
|------|------|----------|
| 模糊提问 | "作业"、"显卡" | 返回澄清请求，提示用户补充说明 |
| 多意图提问 | "排队 + 报错"、"sbatch + 分区" | 逐一分点回答多个问题 |
| 无效/非法提问 | 空输入、纯标点、无关内容 | 空/标点 → `invalid`；无关 → `out_of_scope` |
| 长文本提问 | 超长描述（数百字） | 回答长度达标，命中 GPU/显存关键词 |
| 代码相关问题 | 求 sbatch 脚本、squeue 命令 | 回答含 `#SBATCH`、`--gres`、`squeue` |

附加行为：无 `api_key` 抛 `ValueError`、调用次数统计、Unicode/表情容错、回答质量合格率 ≥ 90%（生成报告）。

### 3.2 检索召回率测试（test_retrieval_recall.py，33 个用例）

- 模拟 20 条中文知识库条目（QOS / CUDA / conda / 排队 / sbatch 等）。
- 15 个典型查询，ground truth 由知识库定义。
- **验收指标**：top-3 召回率 ≥ 90%、top-5 召回率 ≥ 95%（实测均 100% 通过）。
- 生成 `retrieval_recall_report.json`，含逐查询 top-3/top-5 命中明细。

### 3.3 流式输出测试（test_streaming.py，8 个用例）

- 分块算法：英文按词、中文按 2 字，能无损重建原文。
- **首 token 延迟 ≤ 500ms** 验收。
- 逐 token 顺序、无丢失、chunk 非空。
- 中断场景（客户端断开后残留部分返回）与异常场景（上游报错向调用方传播）。

### 3.4 对话管理测试（test_dialog_management.py，13 个用例）

- 会话新建 / 获取 / 删除。
- **多轮上下文累积**，最近 **10 轮**裁剪（15 轮 → 保留后 10 轮）。
- 按 user/assistant 角色拼接上下文。
- **过期 1h** 自动失效。
- 异常中断后基于已存历史恢复、多用户会话隔离。
- 覆盖计划要求的新建/恢复/超时/异常中断 4 个场景。

### 3.5 缓存命中率测试（test_cache_hit_rate.py，11 个用例）

- MD5(query + prompt) 缓存键：确定性、query/prompt 区分、32 位 hex。
- 缓存有效期 30 分钟（TTL 断言）。
- **20 个常见问题 × 重复 2 次**：第二轮全命中，整体命中率 50%，满足验收目标 ≥ 20%。
- 不同 query 不互相污染（全不同 query 命中率为 0）。

---

## 四、Mock 替换说明

所有测试中的 Mock（`MockLLMClient`、`MockVectorStore`、`MockStreamer`、`MockSessionStore`、`MockCache`）
在文件 docstring 中均标注了对应计划中的真实模块：

| Mock | 对应的真实模块（A/B 实现后替换） | 接口约定 |
|------|----------------------------------|----------|
| `MockLLMClient.ask()` | B: `llm/client.py` | 返回 `{answer, category, tokens}` |
| `MockVectorStore.search()` | B: `llm/vector_store.py` + `rag_engine.py` | 返回 top-n 条目 id 列表 |
| `MockStreamer.stream()` | A: `streaming.py` | SSE 异步逐块输出 |
| `MockSessionStore` | A: `dialog/session.py`（Redis） | `create/get/append_turn/delete` |
| `MockCache` | B: `llm/cache.py`（Redis） | `get/set` + hit/miss 计数 |

A、B 实现后，只需将各测试文件首部的 `MockXxx` 替换为 `from src.xxx import ...`，
保持方法签名与返回结构一致即可复用全部验收用例。

---

## 五、遗留说明

- 当前 `src/llm/`、`src/dialog/` 仅有空包，真实实现待第 3 周 A、B 联调。
- 本报告对应计划第 3 周角色 D 任务：LLM 调用测试、检索召回率、流式输出 + 对话管理、缓存命中率、文档整合，均已按周目标完成。
