# 第 5 周 E2E 10 场景预演清单（留痕基准）

> 口径来源：project_plan 周五「10 个复杂场景（修改参数/换分区/加GPU/改时长）」类目
> + D 的 test_report_week5 §五 改写流程契约。plan 只给类目，据此自拟为
> 「改写主线 × 回退 × 边界」三维 10 条。
> 预演方式：8001 端口 `--workers=1` 独立实例，逐场景发 HTTP 请求，记录状态序列与差分。
> 8000 为用户常驻旧代码（无 /api/script），不参与预演。
> 全量口径：879 passed / 3 failed / 26 error / 1 skipped（预存），零回归。

## 评审修正记录（2026-08-16 定稿）

- ① 场景 1 断言改：`-p` 用 **replaced 配对**（不是 removed/added）；`--gres=gpu:4` 仅当原脚本无 gres 行时才为 added。
- ② 场景 8 钉死 **HTTP 404**（None 是 service 内部语义，HTTP 层为 404）；追加 **delete→再访问 404** 覆盖 DELETE 端点。
- ③ 场景 6 回退次数：**实机核验**后修正——压栈只在状态转换时发生（_sync 里 state!=target 才 update_state），collect 因目标态=当前态 COLLECT **不压栈**。start→identify→2×collect→confirm 后栈深 3，**回退 3 次到 INIT**（3→2→1→0）。原假设"start+collect 各 1=3"方向对但理由错，以实机为准。
- ④ 场景 2 export 追加断言：`Content-Disposition` filename（job_name=train → `train.sbatch`）。
- ⑤ 分区值 GPU-RTX5090/CPU-6530 换真实口径 Students/GPU（本层无分区校验器，任何字符串可过；换真实值仅为记录像样，不影响判定）。

## 实机核验补正（回退语义，供场景 5/6/7 断言）

用真实实现逐步追踪（service，ttl=0）：
```
start                        → IDENTIFY, depth=1   (压 INIT 快照)
identify(改分区+改GPU)        → COLLECT, depth=2   (压 IDENTIFY 快照)
collect(partition)           → COLLECT, depth=2   (不分叉，不压栈)
collect(time)                → COLLECT, depth=2   (不分叉，不压栈)
confirm                      → CONFIRM, depth=3   (压 COLLECT 快照)
rollback#1                   → COLLECT, depth=2
rollback#2                   → IDENTIFY, depth=1  (changes 恢复为 identify 时的 {partition,gres})
rollback#3                   → INIT, depth=0      (changes 清空)
```
**要点**：rollback 恢复的是**最近一次压栈时的字段快照**（如 rollback 到 IDENTIFY 时 changes 是 identify 提交的值，非 collect 改后值）——符合"快照回退"契约，写进场景 5/6/7。

---

## 改写主线（场景 1-4，覆盖 plan 四类必选）

### 场景 1：完整改写流程
- **序列**：start → identify(改分区+改GPU) → collect(partition=GPU) → collect(gres=gpu:4) → confirm → apply → finish
- **断言**：状态序列 INIT→IDENTIFY→COLLECT→CONFIRM→APPLY→DONE；modified 含新分区/GPU；diff 的 `-p` 走 **replaced 配对**；`--gres=gpu:4` 原脚本无 gres 行时记 **added**

### 场景 2：仅改分区
- **序列**：start → collect(partition=GPU) → confirm → export
- **断言**：只替换 `-p` 其余不变；export 返回 .sbatch 内容 + **`Content-Disposition` filename**（job_name=train → train.sbatch）

### 场景 3：改 GPU 数量
- **序列**：start(含 `--gres=gpu:1`) → collect(gres=gpu:4) → confirm
- **断言**：`--gres=gpu:1` → `--gres=gpu:4` 替换成功，非 SBATCH 行保留
- **⚠️ 预演修正**：原 S0 脚本无 gres 行 → gres 是 no-op（_replace_param 只替换不新增）。
  改用含 `--gres=gpu:1` 的脚本验证"数量改变"才是本场景真实意图。

### 场景 4：改时长
- **序列**：start → collect(time=24:00:00) → confirm
- **断言**：`-t 24:00:00` 替换

## 回退（场景 5-7）

### 场景 5：收集后回退
- **序列**：start → collect(A) → collect(B) → rollback
- **断言**：回退后回到最近压栈点，changes 恢复对应快照（注意：非逐 collect 回退，是逐状态转换回退）

### 场景 6：多步回退到 INIT
- **序列**：start → identify → collect(A) → collect(B) → confirm → rollback ×3
- **断言**：3 次回退到 INIT（depth 3→0），changes 清空

### 场景 7：回退后继续（分支）
- **序列**：start → collect(A) → rollback → collect(C) → confirm
- **断言**：回退后能重新分叉走新路径，结果正确（C 生效）

## 边界（场景 8-10）

### 场景 8：空脚本/不存在会话/删除
- **序列**：start(空脚本) 或访问不存在 sid → **HTTP 404**；DELETE → 再访问 404
- **断言**：空脚本可 start；不存在会话 HTTP 404；DELETE 后 404

### 场景 9：无修改确认
- **序列**：start → confirm（无 collect）
- **断言**：confirm 返回原脚本，diff 无变化

### 场景 10：generate → suggest 联动
- **序列**：/generate(minimal_cpu) → /suggest(补齐字段)
- **断言**：生成脚本 + 建议补全 + 非 SBATCH 行保留

> 覆盖说明：TTL 过期不占预演名额——已由 service 14 例中假时钟单测覆盖，plan 周五类目不含 TTL。所有场景只走改写路径，不依赖 B 的 LLM 生成。
---

## 预演执行记录（2026-08-16，8001 实例 --workers=1）

**结果：10/10 场景全部通过**（修正断言口径后）。逐场景：

| 场景 | 结果 | 备注 |
|---|---|---|
| sc1 完整流程 | ✅ | 状态序列 identify→collect→collect→confirm→apply→done，consistent 全程 True |
| sc2 仅改分区 | ✅ | `-p` replaced 生效；export text/plain + filename=train.sbatch |
| sc3 改GPU数量 | ✅ | `--gres=gpu:1`→`--gres=gpu:4`（Sg 含 gres 行）|
| sc4 改时长 | ✅ | `-t 24:00:00` |
| sc5 收集后回退 | ✅ | 回 identify 态，changes 恢复快照 {partition} |
| sc6 多步回退到INIT | ✅ | 回退到 init，depth=0，changes 清空 |
| sc7 回退后继续 | ✅ | 分支新值 `-t 02:00:00` 生效 |
| sc8 边界 | ✅ | 空脚本 start 200；不存在会话 404；DELETE 204；delete 后 404 |
| sc9 无修改确认 | ✅ | 原脚本原样返回 |
| sc10 generate→parse→suggest | ✅ | 三端联动全通 |

## 预演中发现并记录的 3 个"测试脚本口径"问题（均非代码 bug，已修正断言复跑）

1. **sc2 export Content-Type**：导出是文本下载 `text/plain; charset=utf-8`，非 JSON——脚本误按 JSON 解析会崩。功能正常（filename 正确）。
2. **sc3 gres no-op**：`_replace_param` 只替换已有参数、**不新增**。原 S0 无 gres 行时改 gres 是无操作。改用含 `--gres=gpu:1` 的脚本才体现"数量改变"意图。这是**设计边界**（改写=参数替换，不新增参数行），已在清单 §场景3 注明。
3. **diff 语义**：`-p` 走**整行 replaced 配对**（`["旧行","新行"]`），不是 removed/added——①号评审修正验证成立。added/removed 只在整行增删时出现（如新增 #SBATCH 行）。

## 附带确认

- **回退栈语义**：压栈只在状态转换时发生（_sync 里 state!=target 才 update_state）；collect 因目标态=当前态 COLLECT 不压栈。start→identify→2×collect→confirm 后栈深 3，回退 3 次到 INIT。TTL 由 service 14 例假时钟单测覆盖，不入本次预演。
