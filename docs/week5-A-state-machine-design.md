# 第 5 周 A 侧：对话状态机设计 + 接口合同（Step 0 契约裁决文档）

> **双重身份**：本文既是 project_plan.md 周计划「周一：状态机设计文档（状态图 + 状态转换表）」
> 的交付物，也是开写前对 D 的 4 份验收测试（共 77 用例）的**合同式接口提取与契约裁决**。
> 实现时严格按本文签名/结构执行，替换测试 Mock 后即可复用全部验收用例。
>
> 契约来源（唯一权威）：
> - `tests/test_dialog/test_session_management.py`（19 用例）
> - `tests/test_dialog/test_rollback_branch.py`（14 用例）
> - `tests/test_script/test_script_parse_generate.py`（32 用例）
> - `tests/test_script/test_script_rewrite_flow.py`（12 用例）
>
> 实际用例数按测试函数统计为 **19+14+32+12 = 77**，与 D 的口径一致。

---

## 一、状态定义与转换表（周一交付物主体）

### 1.1 状态图（与 project_plan.md §3.7 一致）

```
                    ┌──────────┐
                    │   INIT   │  ← 用户首次进入脚本改写模式
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │ IDENTIFY │  ← 确认用户想改什么（分区/GPU/时长/全改）
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │ COLLECT  │  ← 逐一收集新参数值（可多步）
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │ CONFIRM  │  ← 展示新旧对比，请用户确认
                    └────┬─────┘
                    ┌────┴─────┐
                    ▼          ▼
               ┌────────┐ ┌──────────┐
               │ APPLY  │ │ ROLLBACK │  ← 用户说"回到上一步"（回退后回到前序状态）
               └────┬───┘ └──────────┘
                    ▼
               ┌──────────┐
               │   DONE   │
               └──────────┘
```

### 1.2 状态转换表

| 当前状态 | 事件 | 目标状态 | 守卫条件 | 动作 |
|---|---|---|---|---|
| INIT | start_rewrite(session_id, script) | IDENTIFY | 总是允许 | 保存 original_script |
| IDENTIFY | identify_changes(session_id, changes) | COLLECT | 会话存在 | 记录 changes；save_step("identify") |
| COLLECT | collect_params(session_id, field, value) | COLLECT（自环） | 会话存在 | changes[field]=value；save_step("collect") |
| COLLECT | confirm_changes(session_id) | CONFIRM | 会话存在 | 应用参数替换生成 modified_script；save_step("confirm") |
| CONFIRM | apply_changes(session_id) | APPLY | 会话存在 | save_step("apply") |
| APPLY | finish_rewrite(session_id) | DONE | 会话存在 | save_step("finish") |
| 任意（非 INIT） | rollback(session_id) | 回退栈栈顶状态 | 栈非空 | pop 快照，恢复 state + collected_fields |
| 任意 | rollback_to_init(session_id) | INIT | 会话存在 | 清空回退栈与 collected_fields |

### 1.3 两套测试契约的状态枚举差异（裁决见 §二）

| 枚举 | 出处 | 成员 |
|---|---|---|
| 7 态版 | test_session_management.py | INIT / IDENTIFY / COLLECT / CONFIRM / APPLY / **ROLLBACK** / DONE |
| 6 态版 | test_rollback_branch.py、test_script_rewrite_flow.py（RewriteState） | INIT / IDENTIFY / COLLECT / CONFIRM / APPLY / DONE |

**裁决**：真实实现采用 **7 态超集**（与 plan 状态图一致）。ROLLBACK 成员保留但 77 个用例中
无任何转换指向它——回退在两份测试里都是**栈操作语义**而非驻留状态。保留成员不影响
6 态测试（其断言不涉及 ROLLBACK）。

---

## 二、契约冲突裁决记录（头号风险的处置）

### 2.1 冲突点清单

| # | 冲突点 | test_session_management | test_rollback_branch |
|---|---|---|---|
| C1 | 回退栈元素类型 | `list[DialogState]`（仅状态） | `list[tuple[DialogState, dict]]`（状态+字段快照） |
| C2 | rollback 是否恢复字段 | 未断言 | 断言恢复到转换前字段（含清空） |
| C3 | 状态转换方法名 | `update_state()` | `transition()` |
| C4 | 管理器容器属性名 | `.sessions` | `.contexts` |
| C5 | TTL 过期 | 有（可配，测试用 ttl=1 + 真实 sleep） | 无 |
| C6 | history 属性 | 有（`list[dict[str,str]]`） | 无 |

### 2.2 裁决：单一超集 DialogContext + 方法同义 + 容器双别名

**C1+C2（关键）**：栈元素统一为 `tuple[DialogState, dict]` 快照。论证——

- File2 的 `rollback()` pop 快照恢复 (state, fields)，是测试的显式断言，必须满足；
- File1 的 `rollback()` 只断言**返回的状态值**（`== COLLECT / IDENTIFY / None`）与
  `len(rollback_stack)`，对元素形状与回退后字段**零断言**；
- 快照实现下 `len()` 不变、返回状态取自快照首元素，File1 全部 19 用例依然通过。

**C3**：`update_state()` 与 `transition()` 实现为**同一逻辑的两个方法名**（内部共享
`_do_transition`），语义 = push 当前快照 → 置新状态 → 返回 True；会话不存在返回 False。

**C4**：容器物理上是一个 dict，同时暴露 `.sessions` 与 `.contexts`（property 别名）。

**C5**：TTL 参数化（默认 3600s），过期判断用**真实时钟**（`time.time`）——File1 超时用例
用 `time.sleep` 实测，注入时钟不能省掉默认真实时钟路径；同时保留 `now_fn` 注入参数供
其他单测加速（与第 3 周 Session 模式一致）。`ttl<=0` 表示不过期（File2 用例不配 TTL，
构造时传 `ttl=0` 即关闭）。get_session 命中时刷新 `last_active`（File1
`test_session_activity_resets_timer` 依赖）；过期会话在 get_session 时**惰性删除**
（File1 `test_expired_session_removed` 断言 `"session-001" not in manager.sessions`）。

**C6**：`history: list[dict[str, str]]` 为超集字段，File2 不使用不报错。

**重复 create**：覆盖旧会话并返回全新 INIT 上下文（File1 `test_create_duplicate_session`
断言 `len(sessions) == 1`）。

---

## 三、对话层契约（dialog/state_machine.py）

```python
class DialogState(Enum):
    INIT = "init"; IDENTIFY = "identify"; COLLECT = "collect"
    CONFIRM = "confirm"; APPLY = "apply"; ROLLBACK = "rollback"; DONE = "done"

@dataclass
class DialogContext:
    session_id: str
    state: DialogState = DialogState.INIT
    collected_fields: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    rollback_stack: list[tuple[DialogState, dict[str, Any]]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    ttl: int = 3600
```

### 管理器方法签名（超集类 DialogManager）

| 方法 | 签名 | 关键语义 |
|---|---|---|
| `__init__` | `(ttl: int = 3600)` | ttl<=0 不过期；File2 场景构造时传 ttl=0 |
| `create_session` | `(session_id: str) -> DialogContext` | 覆盖式创建，state=INIT |
| `get_session` | `(session_id: str) -> DialogContext \| None` | 不存在/过期→None；过期惰性删除；命中刷新 last_active |
| `update_state` | `(session_id: str, new_state: DialogState) -> bool` | push (当前状态, 字段快照) → 置新状态 |
| `transition` | 同上 | `update_state` 同义方法 |
| `collect_field` | `(session_id, field_name: str, value: Any) -> bool` | 写入 collected_fields，不入栈 |
| `rollback` | `(session_id: str) -> DialogState \| None` | pop 快照恢复 state+fields，返回恢复后状态；空栈/无会话→None |
| `rollback_to_init` | `(session_id: str) -> bool` | 清栈+清字段+state=INIT；无会话→False |
| `get_rollback_depth` | `(session_id: str) -> int` | len(rollback_stack)；无会话→0 |
| `delete_session` | `(session_id: str) -> bool` | 存在删除→True，否则 False |
| 属性 | `.sessions` / `.contexts` | 同一容器的双别名（测试直接索引与 in 判断） |

### 与第 3 周对话层的关系

- `src/dialog/session.py`（Session，对话历史 + 轮数截断 + TTL）与 `src/dialog/store.py`
  （SessionStore Protocol + MemorySessionStore）**保持不动**（832 基线内，ruff 已清洗）；
- 第 5 周状态机为**并行新层**，通过 session_id 与对话历史关联，不合并两个上下文模型；
- Redis：pyproject 已有 `redis>=5.0.0`，但 D 的用例全是内存行为且本地无 redis server——
  本周实现内存存储，store 抽象沿用第 3 周 Protocol 模式预留 Redis 后端切换入口
  （诚实口径：Redis 后端预留未启用）。

---

## 四、解析器契约（script/parser.py，A 实现）

```python
class SbatchParser:
    def parse(self, script_content: str) -> dict[str, str]: ...
```

- 逐行匹配 `#SBATCH\s+(.+)`；
- 含 `=`：`partition("=")` 切分，key `lstrip("-")`，两侧 strip；
- 不含 `=`：split 取 `parts[0].lstrip("-")` 与 `parts[1]`；
- **短选项保留原始键名，不做别名映射**（测试断言 `result["p"]`/`["c"]`/`["t"]`/`["J"]`，
  长选项为 `["partition"]`/`["qos"]`/`["gres"]`/`["mem"]`）；
- 空脚本 / 无 #SBATCH 行 → `{}`。

## 五、生成器契约（script/generator.py + script/templates.py，B 名义、A 代做）

```python
@dataclass
class ScriptTemplate:
    name: str; description: str; defaults: dict[str, str]

class ScriptGenerator:
    def generate(self, template_name: str, overrides: dict[str, str] | None = None) -> str: ...
```

- 5 模板：`minimal_cpu` / `gpu_single` / `gpu_multi` / `cpu_long` / `debug_interactive`，
  defaults 逐值以 test_script_parse_generate.py L24-81 为准（分区 Students、
  qos_stu_default / qos_stu_medium_2gpu / qos_stu_cpu_long 等与真实平台校准值一致）；
- `defaults.copy()` 后 `update(overrides)`；未知模板 `raise ValueError(f"Unknown template: {name}")`
  （测试用 `match="Unknown template"`）；
- 渲染顺序固定：`#!/bin/bash` → `-J` → `-p` → `--qos=` → `--gres=` → `-c` → `--mem=` → `-t`
  → 空行 → `# Your commands here`（短/长选项格式与测试子串断言一一对应）；
- `ScriptTemplate` 为 A/B 共享定义（plan:260），放 `templates.py` 供 B 后续复用。

## 六、改写流程契约（dialog/flow.py，A 实现）

```python
class RewriteState(Enum):  # 6 态
    INIT="init"; IDENTIFY="identify"; COLLECT="collect"
    CONFIRM="confirm"; APPLY="apply"; DONE="done"

@dataclass
class RewriteContext:
    session_id: str
    state: RewriteState = RewriteState.INIT
    original_script: str = ""
    modified_script: str = ""
    changes: dict[str, Any] = field(default_factory=dict)
    step_history: list[dict[str, Any]] = field(default_factory=list)
```

### ScriptRewriteFlow 方法（容器属性 `.contexts`，测试直接索引）

| 方法 | 签名 | 状态变迁 |
|---|---|---|
| `start_rewrite` | `(session_id, script) -> RewriteContext` | →IDENTIFY，存 original_script |
| `identify_changes` | `(session_id, changes) -> bool` | →COLLECT，save_step("identify", changes) |
| `collect_params` | `(session_id, field_name, value) -> bool` | 停留 COLLECT，save_step("collect", {"field","value"}) |
| `confirm_changes` | `(session_id) -> str \| None` | 应用替换后 →**CONFIRM**，save_step("confirm")，返回 modified |
| `apply_changes` | `(session_id) -> bool` | →APPLY，save_step("apply") |
| `finish_rewrite` | `(session_id) -> bool` | →DONE，save_step("finish") |

- 替换仅覆盖 4 字段映射：`partition→-p` / `time→-t` / `mem→--mem` / `gres→--gres`，
  其他字段静默跳过；
- 替换算法：先试 `{param}=\S+`（等号格式），命中则替换为 `{param}={value}`；否则
  `{param}\s+\S+` 替换为 `{param} {value}`；非 #SBATCH 行不受影响；
- `save_step` 记录 `{"step", "data", "state"}`，**回退不裁剪 step_history**
  （`test_step_history_preserved` 依赖）；
- 边界：无会话 → bool 方法 False / confirm → None；空脚本可 start（original_script=""）；
  changes={} 时 confirm 返回原脚本。

---

## 七、易错断言点（实现时的陷阱清单）

1. **confirm_changes 之后状态是 CONFIRM 不是 APPLY**（Mock 如此，测试不直接断言但
   apply_changes 断言 APPLY——实现若跳态会连锁出错）；
2. **File1 的 rollback 语义兼容**：File1 的 update_state 只压状态语义，但统一为快照后
   其全部断言（状态值/栈长）不受影响——实现时不要为 File1 单开简化栈；
3. **parse 短键不映射**：`-p` 就是 `"p"`，不是 `"partition"`；
4. **generator 行格式严格**：`-p X`（空格）vs `--qos=X`（等号）不可互换，15 个组合用例
   全是子串精确匹配；
5. **step_history 只增不减**；
6. **get_session 命中必须刷新 last_active**（活动重置计时器用例）；
7. **过期删除要真删容器条目**，不是仅返回 None；
8. **重复 create_session 覆盖**且容器计数为 1。

## 八、实现层次与顺序（依赖拓扑）

| 层 | 文件 | 依赖 | 锁定用例 |
|---|---|---|---|
| 1 | `src/script/parser.py` | 无 | 解析 7 |
| 2 | `src/script/templates.py` + `generator.py` | 无 | 生成 7 + 组合 15 + 验证 3 |
| 3 | `src/dialog/state_machine.py` | 无（模式复用第 3 周 store） | 19 + 14 |
| 4 | `src/dialog/flow.py` | parser | 12 |
| 5 | 集成：`src/pipeline.py` 追加分支 + 新增 `src/api/routes_script.py` | 全部 | 周四 v3.0 + 周五 10 场景 |

每层完成即替换对应测试文件顶部的 Mock 定义为 `from src.xxx import ...`（连同内联的
DialogState/DialogContext/RewriteState/RewriteContext 一并替换），跑通该层用例再进下一层。

## 九、验收口径（诚实记录）

- A 侧直接责任：45 用例（19 + 14 + 12）；
- B 名义由 A 代做：32 用例（parser 归属 plan 写 A、测试注释写 B，用户已拍板 A 全做）；
- 全量口径 77 用例 + 既有基线 832 passed 零回归；
- 周五 10 场景端到端仅覆盖**改写路径**（不依赖 B 的 LLM 辅助生成），生成类场景另行标注。

## 十、开工基线状态记录（2026-08-16 更新）

- 第 4 周 PR 已合并入远程 main（merge commit `422aea0`，Merge pull request #4 from
  rose598/feat/A-week4-llm），网络恢复并验证完毕；
- 本地已切至 `main` 分支并与远程同步，工作区干净；
- 基线确认：832 passed / 3 failed / 26 error / 1 skipped（failed 与 error 均为预存），零回归；
- 77 验收用例全部在库（tests/test_dialog/ 与 tests/test_script/ 四文件），各文件内联
  Mock 待对应模块实现后逐层替换；
- 实现自 `src/dialog/state_machine.py` 起步，按模块粒度提交（[dialog]/[script] 前缀）。
