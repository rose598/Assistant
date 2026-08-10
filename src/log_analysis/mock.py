"""日志假数据模拟器。

根据平台真实 scontrol / sacct / squeue / sinfo 输出格式,生成模拟的
作业日志数据,涵盖多种常见错误场景,用于在接入真实 SSH 之前测试日志解析,
错误分类等逻辑(第 1 周 A 的任务,为第 2 周的真实日志对接和日志解析器打基础)。

输出字段与后续日志解析器(B 第 2 周)对齐:
JobId, JobName, JobState, ExitCode, Partition, QOS, Command, WorkDir,
Reason, NodeList, StartTime, EndTime 等。

用法::

    from src.log_analysis.mock import MockJob, load_mock_jobs
    jobs = load_mock_jobs()
    print(jobs[0].to_scontrol())     # 单个作业的 scontrol 格式
    print(render_sacct(jobs))        # 汇总的 sacct 表格
    print(render_squeue(jobs))       # 排队/运行视图
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

# 真实平台分区与 QOS(来自知识库 qos_table.json)
PARTITIONS: list[str] = ["Students", "CPU-6530", "GPU-RTX5090"]
QOS_LIST: list[str] = [
    "qos_stu_default",
    "qos_stu_small",
    "qos_stu_medium_2gpu",
    "qos_stu_long",
    "qos_stu_cpu_long",
]

# 常见作业状态码(与 Slurm 速查一致)
JOB_STATES: list[str] = ["PD", "R", "CG", "CD", "F", "CA"]


@dataclass
class MockJob:
    """一条模拟作业记录，字段与真实 scontrol show job 对齐。"""

    job_id: int
    job_name: str
    job_state: str  # PD / R / CG / CD / F / CA
    exit_code: str  # 如 "0:0" 成功, "1:0" 失败, "137:0" OOM 被杀
    partition: str
    qos: str
    command: str
    workdir: str
    reason: str
    node_list: str = ""
    cpus: int = 4
    mem: str = "16G"
    gres: str = "gpu:1"
    walltime: str = "04:00:00"
    start_time: str = "2026-05-21T10:00:00"
    end_time: str = "2026-05-21T14:00:00"
    submit_time: str = "2026-05-21T09:59:00"
    error_type: str = ""  # 错误场景标签,便于测试断言

    # ---- 场景渲染 ----
    def to_scontrol(self) -> str:
        """渲染为 `scontrol show job <id>` 的输出片段。"""
        lines = [
            f"JobId={self.job_id} JobName={self.job_name}",
            f"   UserId=scc_stu({self.job_id}0001) GroupId=scc_students",
            f"   JobState={self.job_state} Reason={self.reason}",
            f"   Partition={self.partition} QOS={self.qos}",
            f"   Command={self.command}",
            f"   WorkDir={self.workdir}",
            f"   SubmitTime={self.submit_time}",
            f"   StartTime={self.start_time} EndTime={self.end_time}",
            f"   NodeList={self.node_list or 'None'}",
            f"   ExitCode={self.exit_code}",
            f"   TRES=cpu={self.cpus},mem={self.mem},gres/{self.gres}",
        ]
        return "\n".join(lines)

    def to_sacct_row(self) -> list[str]:
        """返回 sacct 表格的一行原始字段。"""
        return [
            str(self.job_id),
            self.job_name,
            self.job_state,
            self.exit_code,
            self.partition,
            self.start_time,
            self.end_time,
            self.node_list or "None",
        ]


# ---- 预置错误/场景数据 ------------------------------------------------------

def _build_scenarios() -> list[MockJob]:
    """构建一批覆盖常见场景的模拟作业。"""
    u = "scc_stu"
    common_ok: dict[str, Any] = {
        "partition": "Students",
        "qos": "qos_stu_default",
        "command": "/home/scc/stu/train.sbatch",
        "workdir": f"/home/{u}/run1",
        "cpus": 4,
        "mem": "16G",
        "gres": "gpu:1",
    }

    def mk(**overrides: Any) -> dict[str, Any]:
        """基于 common_ok 合并覆盖字段,返回完整 kwargs 字典。"""
        return {**common_ok, **overrides}

    return [
        # 场景 1: QOS 运行时间超限
        MockJob(
            job_id=1001,
            job_name="train_qos_wall",
            job_state="F",
            exit_code="1:0",
            reason="QOSMaxWallDurationPerJobLimit",
            **common_ok,
            error_type="qos_wall_limit",
        ),
        # 场景 2: QOS CPU 数超限(提交被拒)
        MockJob(
            job_id=1002,
            job_name="train_qos_cpu",
            job_state="CA",
            exit_code="0:0",
            reason="QOSMaxCpuPerUserLimit",
            **mk(cpus=8, gres="gpu:1"),
            error_type="qos_cpu_limit",
        ),
        # 场景 3: GPU 显存 OOM
        MockJob(
            job_id=1003,
            job_name="train_oom",
            job_state="F",
            exit_code="137:0",
            reason="NonZeroExitCode",
            **mk(gres="gpu:5090"),
            error_type="gpu_oom",
        ),
        # 场景 4: 环境缺失(conda 未激活 / ModuleNotFoundError)
        MockJob(
            job_id=1004,
            job_name="train_env",
            job_state="F",
            exit_code="1:0",
            reason="NonZeroExitCode",
            **mk(gres="gpu:1"),
            error_type="env_missing",
        ),
        # 场景 5: 脚本语法错误 / 路径错误
        MockJob(
            job_id=1005,
            job_name="train_script",
            job_state="F",
            exit_code="2:0",
            reason="NonZeroExitCode",
            **mk(gres="gpu:1"),
            error_type="script_error",
        ),
        # 场景 6: 权限不足
        MockJob(
            job_id=1006,
            job_name="train_perm",
            job_state="CA",
            exit_code="0:0",
            reason="PartitionTimeLimit",
            **mk(gres="gpu:A100"),
            error_type="permission",
        ),
        # 场景 7: 正在排队
        MockJob(
            job_id=1007,
            job_name="train_wait",
            job_state="PD",
            exit_code="0:0",
            reason="Resources",
            **mk(gres="gpu:A100"),
            error_type="queued",
        ),
        # 场景 8: 正常成功运行
        MockJob(
            job_id=1008,
            job_name="train_ok",
            job_state="CD",
            exit_code="0:0",
            reason="None",
            **mk(gres="gpu:5090"),
            error_type="success",
        ),
        # 场景 9: 正在运行
        MockJob(
            job_id=1009,
            job_name="train_running",
            job_state="R",
            exit_code="0:0",
            reason="None",
            **mk(gres="gpu:5090", node_list="anode10"),
            error_type="running",
        ),
        # 场景 10: 磁盘空间不足
        MockJob(
            job_id=1010,
            job_name="train_disk",
            job_state="F",
            exit_code="1:0",
            reason="No space left on device",
            **mk(gres="gpu:1"),
            error_type="disk_full",
        ),
        # 场景 11: 内核 / 指令集兼容问题
        MockJob(
            job_id=1011,
            job_name="train_kernel",
            job_state="F",
            exit_code="132:0",
            reason="Illegal instruction",
            **mk(gres="gpu:1"),
            error_type="kernel_issue",
        ),
    ]


# ---- 公开入口 ----------------------------------------------------------------

def load_mock_jobs() -> list[MockJob]:
    """返回预置的模拟作业列表（含各种错误场景）。"""
    return _build_scenarios()


def generate_jobs(
    count: int = 12, seed: int | None = None, include_errors: bool = True
) -> list[MockJob]:
    """随机生成 `count` 条模拟作业。

    参数:
        count: 生成条数。
        seed: 随机种子,保证可复现(测试用)。
        include_errors: 是否混入错误场景。
    """
    rng = random.Random(seed)
    jin = range(2000, 2000 + count)
    jobs: list[MockJob] = []
    for i, jid in enumerate(jin):
        state = rng.choice(JOB_STATES)
        exit_code = "0:0"
        reason = "None"
        error_type = ""
        if state == "F":
            exit_code = rng.choice(["1:0", "137:0", "2:0"])
            reason = "NonZeroExitCode"
            error_type = rng.choice(
                ["gpu_oom", "env_missing", "script_error", "qos_wall_limit"]
            )
        jobs.append(
            MockJob(
                job_id=jid,
                job_name=f"job_{i}",
                job_state=state,
                exit_code=exit_code,
                partition=rng.choice(PARTITIONS),
                qos=rng.choice(QOS_LIST),
                command=f"/home/scc/stu/job_{i}.sbatch",
                workdir=f"/home/scc/stu/run{i}",
                reason=reason,
                node_list=f"anode{rng.randint(5, 17)}" if state == "R" else "",
                cpus=rng.choice([4, 8, 16]),
                mem=rng.choice(["16G", "32G", "64G"]),
                gres="gpu:1",
                error_type=error_type,
            )
        )
    return jobs


def render_scontrol(jobs: list[MockJob]) -> str:
    """渲染为 `scontrol show job` 的多作业输出。"""
    return "\n\n".join(j.to_scontrol() for j in jobs)


def render_sacct(jobs: list[MockJob]) -> str:
    """渲染为 `sacct` 表格输出。"""
    header = "JobID|JobName|State|ExitCode|Partition|Start|End|NodeList"
    rows = ["|".join(j.to_sacct_row()) for j in jobs]
    return "\n".join([header, *rows])


def render_squeue(jobs: list[MockJob]) -> str:
    """渲染为 `squeue -u $USER` 的排队/运行视图（仅 PD / R）。"""
    header = "JOBID|PARTITION|NAME|USER|ST|TIME|NODES|NODELIST(REASON)"
    rows = []
    for j in jobs:
        if j.job_state not in ("PD", "R"):
            continue
        rows.append(
            "|".join(
                [
                    str(j.job_id),
                    j.partition,
                    j.job_name,
                    "scc_stu",
                    j.job_state,
                    "0:00",
                    "1",
                    j.node_list or j.reason,
                ]
            )
        )
    return "\n".join([header, *rows])


def render_sinfo() -> str:
    """渲染 `sinfo` 节点状态输出（静态模拟）。"""
    header = "PARTITION|AVAIL|TIMELIMIT|NODES|STATE|NODELIST"
    rows = [
        "Students|up|infinite|13|idle|anode[05-17]",
        "Students|up|infinite|2|mix|anode[11,16]",
        "CPU-6530|up|infinite|8|idle|cnode[01-08]",
        "GPU-RTX5090|up|infinite|6|idle|gnode[01-06]",
        "GPU-RTX5090|up|infinite|1|down|gnode[07]",
    ]
    return "\n".join([header, *rows])


__all__ = [
    "JOB_STATES",
    "PARTITIONS",
    "QOS_LIST",
    "MockJob",
    "generate_jobs",
    "load_mock_jobs",
    "render_sacct",
    "render_scontrol",
    "render_sinfo",
    "render_squeue",
]
