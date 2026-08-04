# 107-Agent 基础功能演示视频脚本

**时长**: 约 5 分钟
**目标**: 展示 107-Agent 算力平台答疑智能体的核心功能

---

## 开场（0:00 - 0:30）

### 画面
- 显示项目 Logo 和标题
- 背景：简洁的科技感动画

### 旁白
> 欢迎使用 107-Agent，USTC 本科生算力平台的智能答疑助手。
> 本项目旨在帮助同学们快速解决 Slurm 作业调度、GPU 使用、环境配置等常见问题。
> 接下来，我们将演示 5 个核心功能场景。

---

## 场景 1：基础问答（0:30 - 1:15）

### 画面
- 打开浏览器，访问 `http://localhost:8000`
- 显示聊天界面

### 操作
1. 在输入框输入：**"如何提交一个 GPU 作业？"**
2. 点击发送按钮
3. 等待回答显示

### 预期结果
```
在 107 算力平台提交 GPU 作业，需要使用 sbatch 命令：

1. 创建作业脚本 job.sh：
   #!/bin/bash
   #SBATCH -J my_gpu_job
   #SBATCH -p Students
   #SBATCH --gres=gpu:1
   #SBATCH -c 4
   #SBATCH --mem 16G
   #SBATCH -t 04:00:00

   conda activate myenv
   python train.py

2. 提交作业：
   sbatch job.sh

3. 查看作业状态：
   squeue -u $USER
```

### 旁白
> 首先演示基础问答功能。
> 用户输入自然语言问题，系统通过知识库检索和意图识别，返回详细的使用指南。
> 回答包含代码块，支持一键复制。

---

## 场景 2：错误诊断（1:15 - 2:00）

### 画面
- 继续在聊天界面

### 操作
1. 输入：**"我的作业报 QOSMaxWallDurationPerJobLimit 错误怎么办？"**
2. 等待回答

### 预期结果
```
QOSMaxWallDurationPerJobLimit 表示作业申请的运行时间超过当前 QOS 的限制。

**原因分析**：
- 默认 QOS（qos_stu_default）限制为 4 小时
- 你的脚本中 #SBATCH -t 参数超过了 4 小时

**解决方案**：
1. 缩短运行时间：
   #SBATCH -t 03:59:00

2. 申请更高 QOS（如需长时间运行）：
   - 访问平台资源页面申请
   - 或使用 long QOS（最长 72 小时）

**参考**：平台资源 - QOS 与资源上限
```

### 旁白
> 第二个场景是错误诊断。
> 系统能够识别常见的 Slurm 错误，并给出针对性的解决方案。
> 每个回答都附带参考文档链接，方便深入学习。

---

## 场景 3：作业查询（2:00 - 2:45）

### 画面
- 切换到 API 文档页面 `/docs`
- 或直接演示 curl 命令

### 操作
1. 展示 Swagger UI 界面
2. 展开 `/api/jobs/{user}` 接口
3. 点击 "Try it out"
4. 输入用户名 `scc123`
5. 点击 Execute

### 预期结果
```json
{
  "user": "scc123",
  "jobs": [
    {
      "job_id": "12345",
      "job_name": "train_resnet",
      "state": "RUNNING",
      "partition": "Students",
      "start_time": "2024-01-01T10:00:00"
    },
    {
      "job_id": "12344",
      "job_name": "data_process",
      "state": "COMPLETED",
      "exit_code": "0:0"
    }
  ],
  "total": 2
}
```

### 旁白
> 第三个场景是作业查询。
> 通过 REST API，可以查询指定用户的最近作业列表。
> 系统自动对接 Slurm 的 sacct 和 squeue 命令，返回结构化的作业信息。

---

## 场景 4：失败诊断（2:45 - 3:30）

### 画面
- 继续在 Swagger UI 或聊天界面

### 操作
1. 输入：**"帮我看看作业 12340 为什么失败了"**
2. 等待诊断结果

### 预期结果
```
已分析作业 12340，发现以下问题：

**诊断结果**：
- 错误类型：GPU 显存溢出（CUDA OOM）
- 置信度：92%
- 错误日志：CUDA out of memory. Tried to allocate 2.00 GiB

**修复建议**：
1. 减小 batch size（推荐）：
   将 --batch-size 64 改为 --batch-size 32

2. 使用混合精度训练：
   python train.py --fp16

3. 清理显存占用：
   nvidia-smi 检查是否有残留进程

**相关 FAQ**：CUDA out of memory 解决方法
```

### 旁白
> 第四个场景是作业失败诊断。
> 系统读取作业的 stderr 日志，通过规则引擎和 LLM 双重判断，自动识别错误类型。
> 并给出具体的修复命令，可以直接复制执行。

---

## 场景 5：命令行使用（3:30 - 4:15）

### 画面
- 切换到终端界面

### 操作
```bash
# 演示命令行交互
$ python -m src.cli

107-Agent CLI v0.1.0
输入问题，输入 'quit' 退出

> 作业一直排队怎么办？

作业排队（状态 PD）的常见原因：

1. **资源不足**：当前分区没有空闲节点
   - 使用 sinfo 查看分区状态

2. **QOS 限制**：可能触发了 QOSMaxJobsPerUserLimit
   - 使用 scontrol show qos 查看限制

3. **优先级较低**：新提交的作业优先级较低

建议：
- 使用 squeue -u $USER 查看排队位置
- 考虑使用 CPU-6530 分区（如果不需要 GPU）

> quit
再见！
```

### 旁白
> 最后演示命令行模式。
> 对于习惯使用终端的同学，可以直接通过 CLI 进行问答。
> 支持交互式多轮对话，无需打开浏览器。

---

## 结尾（4:15 - 5:00）

### 画面
- 显示项目信息页面
- 技术栈列表
- 团队成员

### 旁白
> 以上就是 107-Agent 的核心功能演示。
> 本项目基于 FastAPI + LLM + RAG 技术栈，为本科生提供智能、便捷的算力平台答疑服务。
>
> 技术亮点：
> - 知识库 FAQ 检索，覆盖 50+ 常见问题
> - LLM 自然语言问答，支持多轮对话
> - 日志自动诊断，三类错误 10 个子类
> - 主动推送预警，排队拥堵、空闲提醒
>
> 感谢观看，欢迎反馈建议！

### 画面
- 显示 GitHub 仓库地址
- 联系方式
- 结束

---

## 附录：演示准备清单

### 环境准备
- [ ] 服务已启动：`python src/main.py`
- [ ] 知识库已加载
- [ ] 浏览器已打开 `http://localhost:8000`
- [ ] 终端已准备好

### 测试数据
- [ ] 用户 `scc123` 有历史作业记录
- [ ] 作业 `12340` 有失败日志（CUDA OOM）
- [ ] 模拟数据生成器已运行

### 录屏设置
- [ ] 分辨率：1920x1080
- [ ] 帧率：30fps
- [ ] 关闭无关通知
- [ ] 浏览器隐藏书签栏

---

## 演示命令速查

```bash
# 启动服务
python src/main.py

# 健康检查
curl http://localhost:8000/health

# 测试问答
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "如何提交作业？"}'

# 查询作业
curl http://localhost:8000/api/jobs/scc123

# 诊断作业
curl http://localhost:8000/api/jobs/12340/diagnose

# CLI 模式
python -m src.cli
```
