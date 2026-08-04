# 第4周测试报告 — 日志智能解析 + 主动推送

> 角色 D | 周目标：标注样本数据、分类准确率+混淆矩阵、修复方案可行性、监控+预测模块测试

项目规划第 4 周由角色 A（规则引擎+LLM 双重判断、空闲检测、定时调度器）和
B（收集样本、规则引擎、修复方案生成、推送通道）并行实现，角色 D 负责测试与验收。

---

## 一、交付物清单

| # | 交付物 | 文件 | 用例数 |
|---|--------|------|--------|
| 1 | 标注样本数据 + 分类准确率 + 混淆矩阵 | [test_classification_report.py](../tests/test_log_analysis/test_classification_report.py) | 62 |
| 2 | 修复方案可行性模拟 | [test_fix_simulation.py](../tests/test_log_analysis/test_fix_simulation.py) | 45 |
| 3 | 监控 + 预测模块测试 | [test_monitor_prediction.py](../tests/test_monitor/test_monitor_prediction.py) | 16 |
| 4 | 测试报告文档 | [test_report_week4.md](test_report_week4.md)（本文件） | - |

### 验证结果

```
pytest tests/test_log_analysis/test_classification_report.py \
       tests/test_log_analysis/test_fix_simulation.py \
       tests/test_monitor/                                → 123 passed

ruff check    → All checks passed!
mypy strict   → Success: no issues found
```

---

## 二、标注样本数据 + 分类准确率 + 混淆矩阵

### 样本规模

- **10 个子类**（对齐计划 §3.5）：gpu_oom / memory_oom / time_limit / syntax / path / package_missing / permission_denied / conda_not_found / cuda_driver / kernel
- **65 条标注样本**（每子类 5~8 条），含 ground truth 标签
- 每条样本包含 `sample_id`、`subcategory`、`error_log`（原始错误文本）、`source`

### 双重分类器架构

```
┌──────────────┐     命中（confidence=0.95）
│ 规则引擎      │ ──────────────────────────→ 返回结果
│ 35 条正则     │
└──────┬───────┘
       │ 未命中
       ▼
┌──────────────┐     置信度 ≥ 阈值
│ LLM 兜底     │ ──────────────────────────→ 返回结果
│ 启发式语义    │
└──────┬───────┘
       │ 也未命中 → "unknown"
```

- 规则命中率：对标注样本 > 90%
- 规则 + LLM 总覆盖率：100%（所有样本均有输出）

### 混淆矩阵

输出 `classification_report_week4.json`，含：
- 逐样本准确率明细
- 对角线占比断言 ≥ 85%（验收标准）
- 按子类准确率统计

---

## 三、修复方案可行性模拟

### 设计

- `FixGenerator`：10 个子类各 3~5 条修复命令模板（含注释/命令/SBATCH 指令）
- `MockShell`：逐条执行，三种结果：
  - `skipped`：注释或空行
  - `dangerous_rejected`：含 `rm -rf /` 等危险命令（拒绝执行）
  - `ok`：模拟执行成功

### 测试覆盖

- **40 条修复用例**（每个子类 4 条）
- 全量模拟执行，成功率 ≥ 95%
- 危险命令拦截验证
- 每条用例断言全部命令 `ok`

---

## 四、监控 + 预测模块

### 组件

| 组件 | Mock | 对应计划 |
|------|------|----------|
| 排队监控 | `MockQueueMonitor` | 排队 > 20 或 等待 > 30min → 预警 |
| 空闲检测 | `MockIdleDetector` | idle 占比 > 60% → 触发 |
| 空闲预测 | `MockPredictionEngine` | 7 天滑动窗口加权平均 |
| 定时调度 | `MockScheduler` | 支持 4 个 crontab 风格任务 |
| 推送 | `MockNotifier` | wecom_bot / email / ws 三种通道 |

### 测试场景

- 排队正常/拥堵/长等待/双预警
- 空闲高/低/0 节点
- 预测冷启动/有历史/过期
- 调度器间隔触发/全量统计
- 推送三通道/P0 优先级
- 端到端集成（排队→预警→推送 完整链路）

---

## 五、Mock 替换说明

| Mock | 对应真实模块 | 接口约定 |
|------|-------------|----------|
| `RuleEngine` | B: `log_analysis/log_rule_engine.py` | `classify(log) → {subcategory, method, confidence}` |
| `MockLLMClassifier` | A: `log_analysis/error_classifier.py` (LLM fallback) | `classify(log) → {subcategory, method, confidence}` |
| `DualClassifier` | A+B 集成 | `classify(log)` 自动路由 |
| `FixGenerator` | A: `log_analysis/fix_generator.py` | `generate(subcategory) → list[str]` |
| `MockShell` | A: `log_analysis/ssh_client.py` | `execute(cmd) → {ok, output, status}` |
| `MockQueueMonitor` | A: `monitor/queue_monitor.py` | `check(snapshot) → list[str]` |
| `MockIdleDetector` | A: `monitor/idle_detector.py` | `check(nodes) → dict` |
| `MockPredictionEngine` | A: `monitor/prediction.py` | `feed + predict` |
| `MockScheduler` | A: `monitor/scheduler.py` (APScheduler) | `add_job + tick` |
| `MockNotifier` | A: `monitor/notifier.py` | `send(event, channel, msg, priority)` |
