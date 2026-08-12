# 平台日志接口调研（第 1 周 · A）

> 目标：分析平台 Slurm 的 `scontrol` / `sacct` / `squeue` / `sinfo` 输出格式，
> 确定日志解析所需的字段与方案，作为第 2 周 SSH 客户端对接与日志解析器的依据。
>
> 所属阶段：第 1 周 A 的任务。产出：本调研文档 + 假数据模拟器
> （`src/log_analysis/mock.py`）。

## 1. 调研结论速览

| 命令 | 用途 | 关键字段 | 对应解析场景 |
|------|------|----------|--------------|
| `scontrol show job <id>` | 单作业详情 | JobId, JobName, JobState, Reason, ExitCode, Partition, QOS, Command, WorkDir, NodeList, TRES | 失败原因定位 |
| `sacct` | 作业历史汇总 | JobID, JobName, State, ExitCode, Partition, Start, End, NodeList | 历史成功率、统计 |
| `squeue -u $USER` | 排队/运行视图 | JOBID, PARTITION, ST, TIME, NODELIST(REASON) | 实时状态、排队检测 |
| `sinfo` | 节点状态 | PARTITION, AVAIL, TIMELIMIT, NODES, STATE, NODELIST | 空闲检测、拥堵预警 |

## 2. 各命令输出格式与解析方案

### 2.1 `scontrol show job <job_id>`

格式为 `Key=Value` 键值对，一行一个作业、续行以空格缩进开头。
解析方案：**按行拆 Key=Value；续行字段与上一作业合并**；遇到新的 `JobId=` 视为新作业起点。

```text
JobId=1008 JobName=train_ok
   UserId=scc_stu(10080001) GroupId=scc_students
   JobState=CD Reason=None
   Partition=Students QOS=qos_stu_default
   Command=/home/scc/stu/run1/train.sbatch
   WorkDir=/home/scc/stu/run1
   SubmitTime=2026-05-21T09:59:00
   StartTime=2026-05-21T10:00:00 EndTime=2026-05-21T14:00:00
   NodeList=anode10
   ExitCode=0:0
   TRES=cpu=4,mem=16G,gres/gpu:5090
```

需要提取的字段（与 B 第 2 周日志解析器对齐）：

| 字段 | 说明 |
|------|------|
| `JobId` / `JobName` | 作业标识 |
| `JobState` | PD/R/CG/CD/F/CA |
| `ExitCode` | `主:次` 形式，`0:0` 成功 |
| `Partition` / `QOS` | 分区与资源方案 |
| `Command` / `WorkDir` | 命令与工作目录 |
| `Reason` | 排队或失败原因（如 `QOSMaxWallDurationPerJobLimit`） |
| `NodeList` | 计算节点 |
| `TRES` | 申请资源（cpu/mem/gres） |

### 2.2 `sacct`

面向汇总统计的字段化表格（以 `|` 或空格分隔）。
解析方案：按字段分隔切分；`JobID` 可能含 `.batch` 等子任务后缀（如 `1008.batch`），需取作业主 ID。

### 2.3 `squeue -u $USER`

实时排队/运行视图。`NODELIST(REASON)` 列：排队时显示原因（`Resources` 等），
运行时显示节点。用于第 4 周排队拥堵预警。

### 2.4 `sinfo`

节点状态：`STATE` 列为 `idle / mix / comp / down / drng`。
用于空闲检测与资源推荐。

## 3. 常见错误场景 → 判定依据

模拟器 `src/log_analysis/mock.py` 预置以下场景（`error_type` 标签便于测试断言）：

| error_type | 典型组合（State / Reason / ExitCode） |
|------------|---------------------------------------|
| `qos_wall_limit` | F / QOSMaxWallDurationPerJobLimit |
| `qos_cpu_limit` | CA / QOSMaxCpuPerUserLimit |
| `gpu_oom` | F / NonZeroExitCode / `137:0` |
| `env_missing` | F / NonZeroExitCode / `1:0` |
| `script_error` | F / NonZeroExitCode / `2:0` |
| `permission` | CA / PartitionTimeLimit |
| `queued` | PD / Resources |
| `success` | CD / None / `0:0` |
| `running` | R / None |

## 4. 对接建议（第 2 周）

- 用 `asyncssh` 封装 `scontrol show job` / `sacct` / `squeue` / `sinfo` 四个命令的执行。
- 解析器接口建议：`parse_scontrol(raw) -> list[JobRecord]`，
  `parse_sacct(raw) -> list[JobRecord]`，`parse_squeue(raw) -> list[QueueEntry]`。
- 先用 `mock.py` 生成的数据驱动解析器开发与测试，再切换到真实命令输出验证。