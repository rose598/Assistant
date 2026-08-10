"""日志命令执行与解析层。

基于 SSHClient 执行平台日志命令,并将输出解析为结构化数据:
- `scontrol show job <id>`   -> 单作业详情
- `sacct`                    -> 作业历史汇总
- `squeue -u $USER`          -> 排队/运行实时状态
- `sinfo`                    -> 节点状态

设计要点（鲁棒性）：
- 解析函数为纯函数,输入原始文本、输出结构化对象;字段缺失时填默认值,
  不因单条记录缺字段而整体抛错。
- 执行层可注入 CommandExecutor:真实场景用 SSHClient;测试或无真实账号时
  注入 MockExecutor(基于昨天 log_analysis.mock 的假数据)。
- 未配置 SSH 时能优雅降级:由调用方决定是否回退到 mock 数据。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.log_analysis.ssh_client import (
    CommandExecutor,
    SSHError,
    SSHNotConfiguredError,
)

__all__ = [
    "JobRecord",
    "LogCommandClient",
    "NodeState",
    "QueueEntry",
    "parse_sacct",
    "parse_scontrol",
    "parse_sinfo",
    "parse_squeue",
]


# ---- 结构化数据 --------------------------------------------------------------

@dataclass
class JobRecord:
    """作业记录，字段与日志解析场景对齐。"""

    job_id: str = ""
    job_name: str = ""
    job_state: str = ""  # PD/R/CG/CD/F/CA
    exit_code: str = ""
    partition: str = ""
    qos: str = ""
    command: str = ""
    workdir: str = ""
    reason: str = ""
    node_list: str = ""
    start_time: str = ""
    end_time: str = ""
    submit_time: str = ""

    @property
    def is_failed(self) -> bool:
        """作业是否属于需要诊断的异常。

        判为"异常"的情形：
        - 状态为 F（失败）
        - 退出码非 0（OOM 等被杀）
        - 状态为 CA（取消）但 Reason 是非中性原因（如被 QOS 资源限制拒绝）
        """
        if self.job_state == "F":
            return True
        if self.exit_code:
            main_code = self.exit_code.split(":", 1)[0]
            try:
                if int(main_code) != 0:
                    return True
            except ValueError:
                pass
        # CA + 明确的资源/权限类原因也视为需要诊断
        return bool(
            self.job_state == "CA"
            and self.reason
            and self._reason_is_notable(self.reason)
        )

    @staticmethod
    def _reason_is_notable(reason: str) -> bool:
        """Reason 是否为"值得诊断"的非中性原因。"""
        neutral = {
            "none",
            "resources",
            "caught signal",
            "canceled by user",
            "user canceled",
            "cancelled",
            "",
            "0",
        }
        return reason.strip().lower() not in neutral


@dataclass
class QueueEntry:
    """squeue 排队/运行视图的一行。"""

    job_id: str
    partition: str = ""
    name: str = ""
    user: str = ""
    state: str = ""  # PD/R
    time: str = ""
    nodes: str = ""
    nodelist_or_reason: str = ""


@dataclass
class NodeState:
    """sinfo 节点状态的一行。"""

    partition: str
    state: str = ""  # idle/mix/comp/down/drng
    nodes: int = 0
    nodelist: str = ""
    avail: str = ""
    timelimit: str = ""


# ---- 解析函数(纯函数,便于测试) --------------------------------------------

# 值可含空格(Slurm 的 Reason 常为 "Killed by signal" 等); 值以非空白开始/结尾,
# 延伸到下一个 "Key=" token 之前, 避免把含空格值截断成单词。
_KEY_VALUE_RE = re.compile(r"(\w+)=(\S+(?:\s+\S+)*?)(?=\s+\w+=|\Z)", re.S)


def parse_scontrol(raw: str) -> list[JobRecord]:
    """解析 `scontrol show job` 输出为作业记录列表。

    格式为 ``Key=Value`` 对,一行一个作业、续行以缩进开头,
    遇到新的 ``JobId=`` 视为新作业起点。
    """
    records: list[JobRecord] = []
    current: dict[str, str] | None = None

    for raw_line in (raw or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        kv = dict(_KEY_VALUE_RE.findall(line))
        # 新作业起点(续行的 JobId= 不再重复记录)
        if "JobId" in kv:
            if current is not None:
                records.append(_to_job_record(current))
            current = {"JobId": kv["JobId"], "JobName": kv.get("JobName", "")}
            continue
        if current is None:
            continue
        for key, value in kv.items():
            if key in ("JobId", "JobName"):
                continue
            current[key] = value

    if current is not None:
        records.append(_to_job_record(current))
    return records


def _to_job_record(d: dict[str, str]) -> JobRecord:
    """把扁平 key-value 字典转为 JobRecord，缺失字段填空。"""
    return JobRecord(
        job_id=d.get("JobId", ""),
        job_name=d.get("JobName", ""),
        job_state=d.get("JobState", ""),
        exit_code=d.get("ExitCode", ""),
        partition=d.get("Partition", ""),
        qos=d.get("QOS", ""),
        command=d.get("Command", ""),
        workdir=d.get("WorkDir", ""),
        reason=d.get("Reason", ""),
        node_list=d.get("NodeList", ""),
        start_time=d.get("StartTime", ""),
        end_time=d.get("EndTime", ""),
        submit_time=d.get("SubmitTime", ""),
    )


def parse_sacct(raw: str, sep: str = "|") -> list[JobRecord]:
    """解析 `sacct` 表格输出(字段化,可自定义分隔符)。

    仅收集主作业行(不含 `.batch` / `.extern` 等子任务后缀),
    字段缺失时填默认值,不因单行异常而整体失败。
    """
    records: list[JobRecord] = []
    field_index: dict[str, int] = {}

    lines = (raw or "").splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        parts = [p.strip() for p in stripped.split(sep)]
        # 表头识别
        if (idx == 0 or parts[0] in ("JobID", "JOBID")) and "JobID" in parts:
            field_index = {name.lower(): i for i, name in enumerate(parts)}
            continue
        if not field_index or "jobid" not in field_index:
            continue
        # 跳过子任务行
        job_id = parts[field_index["jobid"]] if field_index["jobid"] < len(parts) else ""
        if "." in job_id:
            continue
        records.append(
            JobRecord(
                job_id=job_id,
                job_name=_get(parts, field_index, "jobname"),
                job_state=_get(parts, field_index, "state"),
                exit_code=_get(parts, field_index, "exitcode"),
                partition=_get(parts, field_index, "partition"),
                start_time=_get(parts, field_index, "start"),
                end_time=_get(parts, field_index, "end"),
                node_list=_get(parts, field_index, "nodelist"),
            )
        )
    return records


def _get(parts: list[str], field_index: dict[str, int], key: str) -> str:
    idx = field_index.get(key)
    if idx is None or idx >= len(parts):
        return ""
    return parts[idx]


def parse_squeue(raw: str, sep: str | None = None) -> list[QueueEntry]:
    """解析 `squeue -u $USER` 输出。

    sep 为 None 时按空白折叠拆分(贴近真实 squeue 的空格定宽输出);
    也可传 "|" 等显式分隔符。
    """
    entries: list[QueueEntry] = []
    idxs: dict[str, int] = {}
    for idx, line in enumerate((raw or "").splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        parts = _split_fields(stripped, sep)
        if idx == 0:
            idxs = {name.lower(): i for i, name in enumerate(parts)}
            continue
        if not idxs or "jobid" not in idxs:
            continue
        entries.append(
            QueueEntry(
                job_id=_get(parts, idxs, "jobid"),
                partition=_get(parts, idxs, "partition"),
                name=_get(parts, idxs, "name"),
                user=_get(parts, idxs, "user"),
                state=_get(parts, idxs, "st"),
                time=_get(parts, idxs, "time"),
                nodes=_get(parts, idxs, "nodes"),
                nodelist_or_reason=_get(parts, idxs, "nodelist(reason)")
                or _get(parts, idxs, "nodelist"),
            )
        )
    return entries


def _split_fields(line: str, sep: str | None) -> list[str]:
    """按分隔符拆分字段；sep 为 None 时按空白折叠拆分。"""
    if sep is None:
        return line.split()
    return [p.strip() for p in line.split(sep)]


def parse_sinfo(raw: str, sep: str | None = None) -> list[NodeState]:
    """解析 `sinfo` 输出。"""
    states: list[NodeState] = []
    idxs: dict[str, int] = {}
    for idx, line in enumerate((raw or "").splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        parts = _split_fields(stripped, sep)
        if idx == 0:
            idxs = {name.lower(): i for i, name in enumerate(parts)}
            continue
        if not idxs or "partition" not in idxs:
            continue
        nodes = _get(parts, idxs, "nodes") or "0"
        try:
            node_count = int(nodes)
        except ValueError:
            node_count = 0
        states.append(
            NodeState(
                partition=_get(parts, idxs, "partition"),
                state=_get(parts, idxs, "state"),
                nodes=node_count,
                nodelist=_get(parts, idxs, "nodelist"),
                avail=_get(parts, idxs, "avail"),
                timelimit=_get(parts, idxs, "timelimit"),
            )
        )
    return states


# ---- 执行层(组合命令) -------------------------------------------------------

class LogCommandClient:
    """封装日志查询命令。

    通过注入的 executor 执行远程命令并解析结果。executor 可为 SSHClient
    (真实)或 MockExecutor(测试/无账号降级)。

    未配置 SSH 时执行器会抛出 SSHNotConfiguredError,调用方可根据策略
    回退到 mock 数据。
    """

    def __init__(self, executor: CommandExecutor) -> None:
        self._executor = executor

    @property
    def executor(self) -> CommandExecutor:
        return self._executor

    async def get_job(self, job_id: int | str) -> JobRecord | None:
        """查询单个作业详情（scontrol show job）。无该作业时返回 None。"""
        cmd = f"scontrol show job {job_id}"
        try:
            result = await self._executor.run(cmd)
        except SSHNotConfiguredError:
            raise
        except SSHError:
            return None
        records = parse_scontrol(result.stdout)
        for rec in records:
            if rec.job_id == str(job_id):
                return rec
        return None

    async def list_recent_jobs(self, limit: int = 20) -> list[JobRecord]:
        """查询最近作业（sacct），返回最近 limit 条。"""
        # 保留表头以便解析列名; -P 管道分隔, -X 丢弃子任务行
        cmd = (
            "sacct --format=JobID,JobName,State,ExitCode,Partition,"
            "Start,End,NodeList -X -P"
        )
        try:
            result = await self._executor.run(cmd)
        except SSHNotConfiguredError:
            raise
        except SSHError:
            return []
        records = parse_sacct(result.stdout)
        return records[:limit]

    async def list_queue(self) -> list[QueueEntry]:
        """查询用户排队/运行作业（squeue）。"""
        cmd = 'squeue -u "$USER" -o "%.18i %.9P %.30j %.8u %.2t %.10M %.6D %R"'
        try:
            result = await self._executor.run(cmd)
        except SSHNotConfiguredError:
            raise
        except SSHError:
            return []
        return parse_squeue(result.stdout, sep=None)

    async def list_nodes(self) -> list[NodeState]:
        """查询节点状态（sinfo）。"""
        try:
            result = await self._executor.run("sinfo")
        except SSHNotConfiguredError:
            raise
        except SSHError:
            return []
        return parse_sinfo(result.stdout, sep=None)
