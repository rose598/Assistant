"""日志命令解析测试.

覆盖 scontrol / sacct / squeue / sinfo 解析及各格式容错.
"""

from __future__ import annotations

from src.log_analysis.commands import (
    JobRecord,
    parse_sacct,
    parse_scontrol,
    parse_sinfo,
    parse_squeue,
)
from src.log_analysis.mock import load_mock_jobs, render_sacct, render_scontrol


class TestParseScontrol:
    """scontrol 解析测试类."""

    def test_single_job(self) -> None:
        """解析单个作业."""
        raw = (
            "JobId=1008 JobName=train_ok\n"
            "   UserId=scc_stu(10080001) GroupId=scc_students\n"
            "   JobState=CD Reason=None\n"
            "   Partition=Students QOS=qos_stu_default\n"
            "   Command=/home/scc/stu/run1/train.sbatch\n"
            "   WorkDir=/home/scc/stu/run1\n"
            "   SubmitTime=2026-05-21T09:59:00\n"
            "   StartTime=2026-05-21T10:00:00 EndTime=2026-05-21T14:00:00\n"
            "   NodeList=anode10\n"
            "   ExitCode=0:0\n"
            "   TRES=cpu=4,mem=16G,gres/gpu:5090"
        )
        recs = parse_scontrol(raw)
        assert len(recs) == 1
        r = recs[0]
        assert r.job_id == "1008"
        assert r.job_state == "CD"
        assert r.qos == "qos_stu_default"
        assert r.node_list == "anode10"

    def test_multiple_jobs(self) -> None:
        """多作业连排解析."""
        raw = (
            "JobId=1 JobName=a\n   JobState=PD Reason=Resources\n"
            "JobId=2 JobName=b\n   JobState=R Reason=None\n   NodeList=n1\n"
            "JobId=3 JobName=c\n   JobState=F Reason=NonZeroExitCode\n   ExitCode=1:0\n"
        )
        recs = parse_scontrol(raw)
        assert len(recs) == 3
        assert recs[0].job_id == "1"
        assert recs[1].job_id == "2" and recs[1].node_list == "n1"
        assert recs[2].job_id == "3" and recs[2].job_state == "F"

    def test_real_mock_render(self) -> None:
        """用 mock 渲染结果解析."""
        jobs = load_mock_jobs()
        recs = parse_scontrol(render_scontrol(jobs))
        assert len(recs) == len(jobs)

    def test_multi_word_reason_kept_whole(self) -> None:
        """含空格的 Reason 值应被完整保留, 而非截断成首词."""
        raw = (
            "JobId=7 JobName=x\n"
            "   JobState=F Reason=Killed by signal 9\n"
            "   Partition=Students QOS=qos_stu_default\n"
            "   ExitCode=137:0\n"
        )
        recs = parse_scontrol(raw)
        assert len(recs) == 1
        assert recs[0].reason == "Killed by signal 9"

    def test_multi_word_command_and_workdir(self) -> None:
        """值为多段(如含空格路径)时也能完整捕获, 且不吞并相邻字段."""
        raw = (
            "JobId=8 JobName=x\n"
            "   JobState=F Reason=NonZeroExitCode\n"
            "   Command=python train.py --data my data set\n"
            "   WorkDir=/home/scc/my dir\n"
            "   Partition=Students\n"
        )
        recs = parse_scontrol(raw)
        assert len(recs) == 1
        assert recs[0].reason == "NonZeroExitCode"
        assert recs[0].partition == "Students"
        assert recs[0].command == "python train.py --data my data set"
        assert recs[0].workdir == "/home/scc/my dir"


class TestIsFailed:
    """is_failed 判定测试类."""

    def test_F_true(self) -> None:
        assert JobRecord(job_state="F").is_failed is True

    def test_exitcode_nonzero(self) -> None:
        assert JobRecord(job_state="R", exit_code="137:0").is_failed is True

    def test_success_false(self) -> None:
        assert JobRecord(job_state="CD", exit_code="0:0").is_failed is False

    def test_ca_with_notable_reason(self) -> None:
        assert JobRecord(job_state="CA", reason="QOSMaxCpuPerUserLimit").is_failed is True
        assert JobRecord(job_state="CA", reason="Resources", exit_code="0:0").is_failed is False


class TestParseSacct:
    """sacct 解析测试类."""

    def test_skips_subtasks(self) -> None:
        """跳过 .batch 子任务行."""
        raw = (
            "JobID|JobName|State|ExitCode|Partition|Start|End|NodeList\n"
            "1001|train_qos_wall|F|1:0|Students|s|e|n\n"
            "1001.batch|batch|F|1:0|Students|s|e|n\n"
            "1002|train_ok|CD|0:0|Students|s|e|n\n"
        )
        recs = parse_sacct(raw)
        ids = [r.job_id for r in recs]
        assert "1001" in ids
        assert "1001.batch" not in ids
        assert "1002" in ids

    def test_mock_render(self) -> None:
        """用 mock 渲染结果解析."""
        jobs = load_mock_jobs()
        recs = parse_sacct(render_sacct(jobs))
        assert len(recs) == len(jobs)

    def test_empty(self) -> None:
        assert parse_sacct("") == []

    def test_missing_fields_no_crash(self) -> None:
        """某行缺列不整体失败."""
        raw = "JobID|State\n1001|F\n1002|CD\n"
        recs = parse_sacct(raw)
        assert len(recs) == 2


class TestParseSqueue:
    """squeue 解析测试类."""

    def test_whitespace(self) -> None:
        """空白分隔解析."""
        raw = (
            "JOBID PARTITION NAME USER ST TIME NODES NODELIST(REASON)\n"
            "1007 Students train_wait scc_stu PD 0:00 1 Resources\n"
            "1009 Students train_running scc_stu R 0:00 1 anode10\n"
        )
        entries = parse_squeue(raw)
        assert len(entries) == 2
        assert entries[0].state == "PD"
        assert entries[0].nodelist_or_reason == "Resources"
        assert entries[1].nodelist_or_reason == "anode10"

    def test_empty(self) -> None:
        assert parse_squeue("") == []

    def test_header_only(self) -> None:
        assert parse_squeue("JOBID PARTITION NAME USER ST TIME NODES NODELIST(REASON)") == []


class TestParseSinfo:
    """sinfo 解析测试类."""

    def test_parse(self) -> None:
        """节点状态解析."""
        raw = (
            "PARTITION AVAIL TIMELIMIT NODES STATE NODELIST\n"
            "Students up infinite 13 idle anode[05-17]\n"
            "Students up infinite 2 mix anode[11,16]\n"
            "GPU-RTX5090 up infinite 1 down gnode[07]\n"
        )
        states = parse_sinfo(raw)
        assert len(states) == 3
        assert states[0].partition == "Students"
        assert states[0].nodes == 13
        assert states[1].state == "mix"
        assert states[2].state == "down"

    def test_non_numeric_nodes(self) -> None:
        """NODES 列非数字时容错为 0."""
        raw = "PARTITION AVAIL TIMELIMIT NODES STATE NODELIST\nStudents up x abc idle n1\n"
        states = parse_sinfo(raw)
        assert states[0].nodes == 0

    def test_empty(self) -> None:
        assert parse_sinfo("") == []
