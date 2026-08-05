# 107-Agent 用户培训材料

> 面向 USTC 本科生算力平台用户的培训指南

---

## 目录

1. [平台简介](#平台简介)
2. [快速开始](#快速开始)
3. [基础功能](#基础功能)
4. [进阶功能](#进阶功能)
5. [高阶功能](#高阶功能)
6. [常见问题](#常见问题)
7. [最佳实践](#最佳实践)

---

## 平台简介

### 什么是 107-Agent？

107-Agent 是 USTC 本科生算力平台（107.ustc.edu.cn）的智能答疑助手，帮助你：

- **快速解决问题**：自然语言提问，获得 Slurm 相关问题的即时解答
- **自动诊断错误**：分析作业失败原因，给出修复方案
- **智能推荐资源**：根据任务类型推荐最优的分区、GPU、时长配置
- **脚本改写辅助**：多轮对话引导你修改 sbatch 脚本

### 访问方式

| 方式 | 地址 | 适用场景 |
|------|------|----------|
| Web 界面 | `http://localhost:8000` | 日常使用 |
| API 接口 | `/api/ask` | 程序调用 |
| 命令行 | `python -m src.cli` | 终端用户 |

---

## 快速开始

### 3 分钟上手

**Step 1**: 打开 Web 界面或命令行

```bash
# Web 方式
# 浏览器访问 http://localhost:8000

# 命令行方式
python -m src.cli
```

**Step 2**: 输入你的问题

```
如何提交一个 GPU 作业？
```

**Step 3**: 查看回答，复制需要的命令

---

## 基础功能

### 1. 智能问答

#### 使用场景

- 不知道如何提交作业
- 遇到报错不知道原因
- 想了解平台的使用方法

#### 示例问题

| 问题类型 | 示例 |
|----------|------|
| 作业提交 | "如何提交 GPU 作业？" |
| 错误诊断 | "CUDA out of memory 怎么办？" |
| 状态查询 | "作业一直排队怎么办？" |
| 命令帮助 | "sbatch 怎么用？" |

#### 回答示例

```
在 107 平台提交 GPU 作业，需要：

1. 创建作业脚本 job.sh：
   #!/bin/bash
   #SBATCH -J my_job
   #SBATCH -p Students
   #SBATCH --gres=gpu:1
   #SBATCH -c 4
   #SBATCH --mem 16G
   #SBATCH -t 04:00:00

   python train.py

2. 提交作业：
   sbatch job.sh

3. 查看状态：
   squeue -u $USER
```

### 2. 作业查询

#### API 调用

```bash
# 查询最近作业
curl http://localhost:8000/api/jobs/scc123

# 限制返回数量
curl "http://localhost:8000/api/jobs/scc123?limit=5"
```

#### 返回结果

```json
{
  "user": "scc123",
  "jobs": [
    {
      "job_id": "12345",
      "job_name": "train_resnet",
      "state": "RUNNING",
      "partition": "Students"
    }
  ],
  "total": 1
}
```

### 3. 错误诊断

#### 自动诊断

```bash
# 诊断失败作业
curl http://localhost:8000/api/jobs/12345/diagnose
```

#### 诊断结果

```json
{
  "job_id": "12345",
  "status": "FAILED",
  "diagnosis": {
    "category": "resource_exhausted",
    "subcategory": "gpu_oom",
    "description": "GPU 显存溢出"
  },
  "suggestions": [
    {"action": "减小 batch_size", "priority": "high"},
    {"action": "使用混合精度", "priority": "medium"}
  ]
}
```

---

## 进阶功能

### 4. 多轮对话

#### 使用场景

- 需要逐步完善问题描述
- 连续追问相关细节
- 修改脚本参数

#### 示例对话

```
用户: 我的作业报错了
助手: 请问是什么错误信息？

用户: CUDA out of memory
助手: 这是 GPU 显存不足。你的脚本用了多大的 batch_size？

用户: 64
助手: 建议改为 32 或 16，或者使用混合精度训练。
```

#### 保持会话

```python
# 使用 session_id 保持上下文
session_id = "my-session-123"

# 第一轮
ask("如何提交作业？", session_id=session_id)

# 第二轮（系统记住上下文）
ask("GPU 分区有哪些？", session_id=session_id)
```

### 5. 脚本改写

#### 使用场景

- 已有脚本，想修改参数
- 不确定参数怎么改
- 需要逐步引导修改

#### 改写流程

```
1. 上传/粘贴原始脚本
2. 告诉系统要修改什么（如"改成 2 张 GPU"）
3. 系统生成修改后的脚本
4. 对比差异，确认应用
```

### 6. 资源推荐

#### 使用场景

- 不知道选哪个分区
- 不确定需要多少 GPU
- 想优化资源配置

#### 推荐结果

```
根据你的任务类型（深度学习），推荐：

方案 1（推荐）：
- 分区: Students
- GPU: 1 卡
- CPU: 4 核
- 内存: 16G
- 时长: 4 小时
- 理由: 适合初学者，资源充足

方案 2：
- 分区: GPU-RTX5090
- GPU: 2 卡
- ...
```

---

## 高阶功能

### 7. 主动推送

#### 订阅预警

```bash
# 订阅排队预警
curl -X POST http://localhost:8000/api/subscription \
  -H "Content-Type: application/json" \
  -d '{
    "user": "scc123",
    "channels": ["wechat"],
    "events": ["queue_alert", "job_complete"]
  }'
```

#### 推送类型

| 事件 | 说明 |
|------|------|
| queue_alert | 排队拥堵预警 |
| idle_notify | 空闲资源提醒 |
| job_complete | 作业完成通知 |

---

## 常见问题

### Q: 如何提交 GPU 作业？

A: 使用 sbatch 命令：

```bash
#!/bin/bash
#SBATCH -J my_job
#SBATCH -p Students
#SBATCH --gres=gpu:1
#SBATCH -c 4
#SBATCH --mem 16G
#SBATCH -t 04:00:00

python train.py
```

提交：`sbatch job.sh`

### Q: 作业一直排队怎么办？

A:
1. 使用 `squeue -u $USER` 查看排队位置
2. 使用 `sinfo` 查看分区空闲情况
3. 考虑切换到其他分区

### Q: CUDA out of memory 怎么解决？

A:
1. 减小 batch_size（如 64→32→16）
2. 使用混合精度：`--fp16`
3. 清理显存：`nvidia-smi` 检查残留进程

### Q: QOSMaxWallDurationPerJobLimit 错误？

A: 作业运行时间超过 QOS 限制：
1. 缩短 `-t` 参数（默认 4 小时）
2. 或申请更高 QOS（long 最长 72 小时）

---

## 最佳实践

### 脚本编写

1. **始终指定资源**：不要依赖默认值
2. **合理设置时长**：留 20% 余量
3. **使用变量**：便于复用脚本

### 错误排查

1. **先看 stderr**：错误信息最详细
2. **检查退出码**：`sacct -j <jobid> -o ExitCode`
3. **询问 Agent**：直接贴错误信息提问

### 资源选择

| 任务类型 | 推荐分区 | GPU | 时长 |
|----------|----------|-----|------|
| 深度学习 | Students | 1 | 4h |
| 科学计算 | CPU-6530 | 0 | 24h |
| 数据分析 | Students | 0 | 4h |
| 调试测试 | Students | 0 | 1h |

---

## 附录

### 常用命令速查

| 命令 | 说明 |
|------|------|
| `sbatch job.sh` | 提交作业 |
| `squeue -u $USER` | 查看我的作业 |
| `scancel <jobid>` | 取消作业 |
| `sinfo` | 查看集群状态 |
| `sacct -j <jobid>` | 查看作业详情 |

### 分区资源

| 分区 | CPU | GPU | 默认时长 |
|------|-----|-----|----------|
| Students | 4 | 1 | 4h |
| CPU-6530 | 8 | 0 | 4h |
| GPU-RTX5090 | 8 | 2 | 4h |

### 联系方式

- 项目仓库：https://github.com/rose598/Assistant
- 问题反馈：创建 GitHub Issue
