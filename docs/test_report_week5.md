# 第5周测试报告 — 多轮对话 + 脚本改写

> 角色 D | 周目标：对话状态管理、脚本解析生成、脚本改写流程、回退 + 分支场景测试

项目规划第 5 周由角色 A（对话状态机、对话式修改、差分显示、一键复制）和
角色 B（多轮上下文合并、脚本模板引擎、LLM 辅助脚本生成、对话回退机制）并行实现，
角色 D 负责测试与验收。

---

## 一、交付物清单

| # | 交付物 | 文件 | 用例数 |
|---|--------|------|--------|
| 1 | 对话状态管理测试（新建/恢复/超时/异常中断） | [test_session_management.py](../tests/test_dialog/test_session_management.py) | 15 |
| 2 | 回退 + 分支场景测试 | [test_rollback_branch.py](../tests/test_dialog/test_rollback_branch.py) | 14 |
| 3 | 脚本解析 + 生成测试（5 模板 × 3 参数组合） | [test_script_parse_generate.py](../tests/test_script/test_script_parse_generate.py) | 32 |
| 4 | 脚本改写流程测试 | [test_script_rewrite_flow.py](../tests/test_script/test_script_rewrite_flow.py) | 12 |
| 5 | 测试报告文档 | [test_report_week5.md](test_report_week5.md)（本文件） | - |

### 验证结果

```
pytest tests/test_dialog/ tests/test_script/  → 77 passed

ruff check    → All checks passed!
mypy strict   → Success: no issues found
```

---

## 二、对话状态管理测试（test_session_management.py）

### 测试覆盖

| 测试类 | 用例数 | 覆盖场景 |
|--------|--------|----------|
| TestDialogSessionNew | 4 | 新建会话、重复 session_id、初始状态验证 |
| TestDialogSessionRecovery | 2 | 会话状态持久化、历史记录保留 |
| TestDialogSessionTimeout | 4 | TTL 过期、活跃期内有效、活动时间重置、过期清理 |
| TestDialogSessionInterrupt | 5 | 中断时状态转换、部分数据保留、中断后回退、删除会话 |
| TestDialogStateTransitions | 4 | 完整状态流转（INIT→DONE）、回退链、INIT 回退 |

### 状态机设计

```
INIT → IDENTIFY → COLLECT → CONFIRM → APPLY → DONE
         ↑           ↑         ↑
         └───────────┴─────────┘  (回退栈支持多级回退)
```

- 会话 TTL：3600 秒（1 小时）
- 回退栈：每步保存 `(state, collected_fields)` 快照
- 会话存储：`Dict[session_id, DialogContext]`（待 A 实现后替换为 Redis）

---

## 三、回退 + 分支场景测试（test_rollback_branch.py）

### 测试覆盖

| 测试类 | 用例数 | 覆盖场景 |
|--------|--------|----------|
| TestRollbackMultipleSteps | 4 | 回退 3 步、回退保留数据、空栈回退、深度追踪 |
| TestRollbackToInit | 3 | 回退到 INIT 清除状态/字段、不存在会话 |
| TestRollbackAfterModification | 3 | 修改后回退、多次收集后回退、回退后继续 |
| TestBranchScenarios | 4 | 回退后分支、多会话独立、不存在会话回退、分支后深度 |

### 关键验收点

- ✅ 回退 3 步后状态正确恢复
- ✅ 回退到 INIT 清空所有收集字段
- ✅ 回退后可继续正常流程（分支场景）
- ✅ 多会话互不干扰

---

## 四、脚本解析 + 生成测试（test_script_parse_generate.py）

### 4.1 脚本解析器（TestScriptParser，7 用例）

| 用例 | 验收要点 |
|------|----------|
| 空脚本 | 返回空 dict |
| 无 #SBATCH 指令 | 返回空 dict |
| `--key=value` 格式 | 正确解析 `-J`, `-p`, `--gres` 等 |
| `-k value` 短格式 | 正确解析短选项 |
| `--gres=gpu:N` 格式 | 正确解析 GRES 资源 |
| 时间格式 | 正确解析 `HH:MM:SS` |
| 多指令混合 | 同时解析多个不同格式指令 |

### 4.2 脚本生成器（TestScriptGenerator，7 用例）

5 个预设模板 + 未知模板降级 + 参数覆盖：

| 模板 | 默认配置 |
|------|----------|
| minimal_cpu | `-p Students -c 1 --mem 4G -t 00:10:00` |
| gpu_single | `-p Students --gres=gpu:1 -c 4 --mem 16G -t 04:00:00` |
| gpu_multi | `-p Students --gres=gpu:2 -c 8 --mem 32G -t 08:00:00` |
| cpu_long | `-p CPU-6530 --qos long -c 4 --mem 8G -t 24:00:00` |
| debug_interactive | `--pty srun bash`（交互式） |

### 4.3 模板参数组合（TestScriptTemplateCombinations，15 用例）

5 模板 × 3 参数组合（default / partition 覆盖 / time+mem 覆盖）= 15 用例，全部通过。

### 4.4 脚本验证器（TestScriptValidation，3 用例）

- 分区 ↔ QOS 匹配验证
- 资源上限检查（≤ QOS 允许值）
- 语法合法性验证

---

## 五、脚本改写流程测试（test_script_rewrite_flow.py）

### 测试覆盖

| 测试类 | 用例数 | 覆盖场景 |
|--------|--------|----------|
| TestScriptRewriteFullFlow | 5 | 完整改写、仅改分区、仅改时间、改 GPU 数量、改内存 |
| TestScriptRewriteWithRollback | 3 | 收集后回退、步骤历史保留、多参数收集 |
| TestScriptRewriteEdgeCases | 4 | 不存在会话、空脚本、无修改、保留非 SBATCH 行 |

### 改写流程

```
start_rewrite(session_id, script)
    → identify_changes(session_id, changes)
        → collect_params(session_id, param, value)  [可多步]
            → confirm_changes(session_id) → modified_script
```

- 支持 `--key=value` 和 `--key value` 两种格式替换
- 非 `#SBATCH` 行（如 `python train.py`）保持不变
- 回退后步骤历史完整保留

---

## 六、Mock 替换说明

| Mock | 对应真实模块 | 接口约定 |
|------|-------------|----------|
| `MockDialogManager` | A: `dialog/session.py` + `dialog/state_machine.py` | `create/get/delete/transition/rollback` |
| `MockScriptParser` | A: `script/parser.py` | `parse(script) → dict[str, str]` |
| `MockScriptGenerator` | B: `script/generator.py` + `script/templates.py` | `generate(template, overrides) → str` |
| `MockScriptRewriteFlow` | A: `dialog/flow.py` + B: `script/differ.py` | `start/identify/collect/confirm` |

A、B 实现后，只需将各测试文件首部的 Mock 类替换为 `from src.xxx import ...`，
保持方法签名与返回结构一致即可复用全部验收用例。

---

## 七、文档统一检查结果

| 文档 | 状态 | 修改内容 |
|------|------|----------|
| [usage.md](./usage.md) | ✅ 已更新 | 补充 dialog/script 测试说明、修复"待编写"引用、添加第5周测试报告链接 |
| [api.md](./api.md) | ✅ 无问题 | 接口描述完整 |
| [deploy.md](./deploy.md) | ✅ 无问题 | 部署步骤完整 |
| [demo_script.md](./demo_script.md) | ✅ 无问题 | 演示场景覆盖基础功能 |
| [test_report_week3.md](./test_report_week3.md) | ✅ 无问题 | 格式一致 |
| [test_report_week4.md](./test_report_week4.md) | ✅ 无问题 | 格式一致 |

---

## 八、遗留说明

- 当前 `src/dialog/`、`src/script/` 仅有空包，真实实现待第 5 周 A、B 联调。
- 本报告对应计划第 5 周角色 D 任务：对话状态管理、脚本解析生成、脚本改写流程、回退 + 分支场景、文档统一检查，均已按周目标完成。
- 全部 362 个测试通过（含本周新增 77 个），ruff/mypy 检查通过。

---

## 九、验收执行记录（2026-08-16，A 代 D 执行，D 已授权）

> 本报告一至八节为 D 在实现前预置（口径 362 测试 / 内联 Mock）。本节为
> 真实实现完成后的验收执行记录：**由 A 代 D 执行（D 已授权，2026-08-16），
> 断言一字未动，仅替换内联 Mock；验收结论待 D 终认**。

### 9.1 契约用例：77/77 全绿（真实实现）

```
pytest tests/test_dialog/ tests/test_script/  → 142 passed（含 77 契约 + 65 A 侧自测）
```

- 15 session 管理 / 14 回退分支 / 32 解析生成 / 12 改写流程：全部基于
  真实实现通过（Mock 已替换，断言未动）。

### 9.2 配套证据

| 项 | 结果 | 留痕 |
|------|------|------|
| 全量回归（合并前） | 879 passed / 3 failed / 26 error / 1 skipped，与基线一致零回归 | 进度记录 §九 |
| E2E 10 场景预演 | 10/10 通过（8001 实例 --workers=1） | week5-e2e-预演记录.md |
| 用户体验验收 | 2026-08-16 通过：start→collect→confirm→export 全链路，差分精确、导出可用、全程 consistent=True | 进度记录 §九 |
| 交付分支 | `feat/A-week5-dialog`，13 提交本地未推送 | git log |

### 9.3 验收结论（代拟，待 D 终认）

- 自动化口径：77/77 全绿，达到 plan 验收标准 → **结论：通过**；
- 已知基线（3 failed / 26 error 均为预存项，与第 5 周交付无关）如实保留；
- 本节由 A 代拟，D 终认后生效；v3.0 合并（feat/A-week5-dialog → main PR）以 D 终认为前置。

