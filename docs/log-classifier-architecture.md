# 日志解析分类器架构设计（规则引擎 + LLM 双重判断，规则优先）

> 第 4 周周一 A 交付物①②。承接 plan §3.5「日志智能解析」与本项目第 2 周已有
> [classifier.py](../src/log_analysis/classifier.py)（规则分类器）。
> 分工：A 提供**架构 + LLM 兜底实现 + 一键修复命令 + 定时调度**；B 提供**规则引擎（30+ 正则）+
> 3 个子类判定器 + 修复方案生成器 + 推送通道**。本文档为两类能力对齐接口契约。

---

## 1. 设计目标与原则

- **规则优先**：毫秒级规则/信号判定先行，避免无谓调用 LLM（省成本、降延迟）。
- **LLM 兜底**：规则未命中或低置信时才调 LLM，提升对"新报错/长错误栈/未列正则"的覆盖率。
- **接口单一**：对外统一收敛为 `ErrorClassification`（第 2 周已定型），上游（`FixGenerator`、
  `/api/jobs/{id}/diagnose`）无需改动。
- **可替换、可关闭**：LLM 未配置/调用失败时优雅降级为纯规则结果，不影响功能。
- **与 B 对齐**：规则细节归 B，A 只依赖"规则输出 `ErrorClassification`"这一稳定接口，
  不硬编码 B 的正则表。

## 2. 整体架构

```
原始作业信息(JobRecord: reason/exit_code/job_name/state ...)
        │
        ▼
┌─────────────────────────┐
│ ① 规则/信号引擎           │  归B(已有 v0: ErrorClassifier)
│   多信号加权 + 知识库错误码  │  毫秒级
└──────────┬──────────────┘
           │
           ├── 命中且 confidence ≥ RULE_CONF_THRESHOLD ──► 直接返回(规则优先)
           │
           └── 未命中/低置信(confidence < 阈值 或 subtype==unknown)
                    │
                    ▼
        ┌─────────────────────────┐
        │ ② LLM 辅助分类            │  归A(本周实现, llm_log_classifier.py)
        │   组装诊断上下文→LLM→解析   │  网络级
        └──────────┬──────────────┘
                   │
                   ├── LLM 分类成功 ──► 合并置信度, 返回 ErrorClassification
                   │
                   └── LLM 不可用/失败/无结果 ──► 返回规则原始结果(不劣化)
```

### 判定流程（伪代码）

```
def classify(record) -> ErrorClassification:
    rule = rule_engine.classify(record)          # 规则优先
    if not _needs_llm(rule):                     # 命中且置信度高
        return rule
    llm_res = llm_classifier.classify(record)    # LLM 兜底
    if llm_res and llm_res.is_known:             # LLM 给出可靠类别
        return llm_res
    return rule                                  # 优雅降级
```

## 3. 接口契约

### 3.1 现有契约（复用，不破坏）

- `ErrorClassifier.classify(JobRecord) -> ErrorClassification`（[classifier.py](../src/log_analysis/classifier.py)）
  - `ErrorClassification`: `category` / `subtype` / `confidence`(0-1) / `signals_hit` / `is_known`
- `JobRecord`（[commands.py](../src/log_analysis/commands.py)）：`job_id / job_name / job_state /
  exit_code / partition / qos / command / workdir / reason / node_list / start_time / end_time / submit_time`
- `LLMClientProtocol.complete(messages) -> LLMResponse`（[client.py](../src/llm/client.py)）
- `create_llm_client(config) -> OpenAILLMClient | MockLLMClient`（[mock_llm.py](../src/llm/mock_llm.py)）

### 3.2 新增：LLM 辅助分类器

```python
class LLMLogClassifier:
    def __init__(self, llm: LLMClientProtocol | None = None,
                 rule_engine: ErrorClassifier | None = None, ...) -> None: ...
    def classify(self, record: JobRecord) -> ErrorClassification: ...   # 供多层判断组合
    async def aclassify(self, record: JobRecord) -> ErrorClassification: ...  # 异步(接真实LLM)

class DualLogClassifier:      # 规则优先 + LLM 兜底的门面
    def __init__(self, rule_engine=None, llm=None, ...): ...
    async def classify(self, record) -> ErrorClassification
    async def aclassify(self, record) -> ErrorClassification
```

### 3.3 判定阈值（Config 可配）

| 配置名 | 默认 | 含义 |
|---|---|---|
| `rule_conf_threshold` | 0.6 | 规则置信度 ≥ 此值直接返回，不再调 LLM |
| `llm_conf_threshold` | 0.5 | LLM 分类结果置信度 < 此值视为不可靠，回退规则 |

## 4. LLM 提示模板

复用 [prompts.py](../src/llm/prompts.py) `LOG_ANALYSIS_TEMPLATE` 体系，新增 `LOG_CLASSIFY_TEMPLATE`：
把作业 status/reason(.err 摘要)/exit_code 送入，要求 LLM 输出**受控 JSON**：

```json
{"category": "oom|script|env|permission", "subtype": "gpu_oom|...", "confidence": 0.9,
 "signals_hit": ["LLM: CUDA out of memory 特征"]}
```

subtype 白名单与 [classifier.py](../src/log_analysis/classifier.py) `SUBTYPE_CATEGORY` 保持一致，
LLM 输出非法类别时落回 `unknown` → 触发规则结果兜底。

## 5. 与 B 的对齐点（挂起，不阻塞）

- 规则引擎的**正则细节**（30+ 条，含三类 12 子类）归 B；A 只消费 `ErrorClassification`，
  因此 B 增强 `ErrorClassifier` 后 A 的 LLM 兜底层自动受益、无需改。
- 子类判定器（资源/脚本/环境）归 B；A 不重复实现分类逻辑，只在规则不足时用 LLM 补。
- `FixGenerator`（修复方案模板）归 B；A 在 Day 4 实现**一键修复命令**时基于其输出拼装可执行命令。

## 6. 验收口径

- 规则+LLM **总覆盖率 ≥ 98%**：在未标注样本集上，`(规则命中 ∪ LLM 命中) / 样本数`。
- 规则仍优先：设 30 个规则已知样本，应 100% 走规则、0 次 LLM 调用（省成本）。
- 降级可测：无 LLM/LLM 抛错时，结果 == 纯规则结果，不 500。
- 集成到 `/api/jobs/{id}/diagnose`：诊断响应带 `channel: "rule"|"llm"|"fallback"`（可选，向后兼容）。