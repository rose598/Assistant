"""失败原因诊断映射测试.

覆盖精确错误码 / 模糊匹配 / 通用兜底三层, 以及成功作业不误报.
"""

from __future__ import annotations

from src.log_analysis.commands import JobRecord, LogCommandClient
from src.log_analysis.diagnoser import JobDiagnoser
from src.log_analysis.mock import load_mock_jobs
from src.log_analysis.mock_executor import MockExecutor


class TestDiagnoser:
    """失败诊断测试类."""

    def setup_method(self) -> None:
        """每个测试前初始化诊断器."""
        self.dg = JobDiagnoser()

    async def _get(self, job_id: int) -> JobRecord:
        """从 mock 获取作业, 断言必存在."""
        rec = await LogCommandClient(MockExecutor()).get_job(job_id)
        assert rec is not None, f"mock 应存在作业 {job_id}"
        return rec

    async def test_exact_code_maps_correct_faq(self) -> None:
        """QOS 运行时间限制映射到 faq-001."""
        rec = await self._get(1001)
        diag = self.dg.diagnose(rec)
        assert diag.is_failed
        assert diag.matched_code is not None
        assert diag.matched_code.code == "QOSMaxWallDurationPerJobLimit"
        assert diag.matched_faq is not None
        assert diag.matched_faq.id == "faq-001"
        assert diag.confidence == 1.0

    async def test_exact_code_cpu_maps_faq_002(self) -> None:
        """QOS CPU 限制(CA 状态)映射到 faq-002."""
        rec = await self._get(1002)
        diag = self.dg.diagnose(rec)
        assert diag.is_failed
        assert diag.matched_code is not None
        assert diag.matched_faq is not None
        assert diag.matched_faq.id == "faq-002"

    def test_success_job_not_failed(self) -> None:
        """成功作业不判为失败."""
        rec = JobRecord(job_state="CD", exit_code="0:0", reason="None")
        diag = self.dg.diagnose(rec)
        assert diag.is_failed is False

    def test_unknown_reason_falls_back_to_generic(self) -> None:
        """未知原因回退到通用方案."""
        rec = JobRecord(
            job_id="8888", job_state="F", exit_code="3:0",
            reason="SomeUnknownWeirdReason", partition="Students",
        )
        diag = self.dg.diagnose(rec)
        assert diag.is_failed
        assert len(diag.solution) > 0

    def test_never_raises_on_missing_fields(self) -> None:
        """极简记录不抛异常."""
        diag = self.dg.diagnose(JobRecord(job_state="F"))
        assert diag.is_failed

    async def test_oom_scenario_solution_nonempty(self) -> None:
        """GPU OOM 场景给出非空方案."""
        rec = await self._get(1003)
        diag = self.dg.diagnose(rec)
        assert diag.is_failed
        assert len(diag.solution) > 0

    def test_all_mock_failed_jobs_get_solution(self) -> None:
        """mock 中所有失败作业都应得到非空方案."""
        total = 0
        for job in load_mock_jobs():
            rec = JobRecord(
                job_id=str(job.job_id), job_state=job.job_state,
                exit_code=job.exit_code, reason=job.reason,
                partition=job.partition, qos=job.qos,
            )
            if rec.is_failed:
                total += 1
                assert len(self.dg.diagnose(rec).solution) > 0
        assert total > 0
