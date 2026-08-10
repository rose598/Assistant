"""/api/jobs 作业查询与诊断端点.

- GET /api/jobs/{user}            查询用户最近作业列表
- GET /api/jobs/{job_id}/diagnose 分析作业失败原因(三层: 诊断 + 分类 + 修复建议)

数据来源:
- 默认走 MockExecutor(未配置真实 SSH 时降级, data_source="mock")
- 配置了 ssh_host/ssh_user 时走真实 SSH (data_source="ssh")

鲁棒性:
- 作业不存在 -> 404
- 作业未失败 -> 返回"无需诊断"而非错误
- SSH 未配置 -> 降级 mock, 响应中明确标注, 不误导用户
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config import get_config
from src.log_analysis.classifier import ErrorClassifier
from src.log_analysis.commands import JobRecord, LogCommandClient
from src.log_analysis.diagnoser import JobDiagnoser
from src.log_analysis.fix_generator import FixGenerator
from src.log_analysis.mock_executor import MockExecutor
from src.log_analysis.ssh_client import SSHNotConfiguredError

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ---- 响应模型 ----------------------------------------------------------------

class JobInfo(BaseModel):
    """作业摘要."""

    job_id: str
    job_name: str = ""
    job_state: str = ""
    exit_code: str = ""
    partition: str = ""
    qos: str = ""
    node_list: str = ""


class DiagnoseInfo(BaseModel):
    """诊断结果."""

    is_failed: bool
    category: str = "unknown"
    subtype: str = "unknown"
    confidence: float = 0.0
    faq_id: str = ""
    advice: str
    commands: list[str] = []
    reason: str = ""


class DiagnoseResponse(BaseModel):
    """作业诊断响应."""

    job: JobInfo
    diagnosis: DiagnoseInfo
    data_source: str = "mock"


# ---- 共享依赖 ----------------------------------------------------------------

def _build_command_client() -> LogCommandClient:
    """构建命令客户端: SSH 可用则用 SSH, 否则 mock 降级."""
    cfg = get_config()
    if cfg.ssh_host and cfg.ssh_user:
        from src.log_analysis.ssh_client import SSHClient

        return LogCommandClient(SSHClient(host=cfg.ssh_host, user=cfg.ssh_user))
    return LogCommandClient(MockExecutor())


def _to_job_info(rec: JobRecord) -> JobInfo:
    """把 JobRecord 转为响应模型."""
    return JobInfo(
        job_id=rec.job_id or "",
        job_name=rec.job_name or "",
        job_state=rec.job_state or "",
        exit_code=rec.exit_code or "",
        partition=rec.partition or "",
        qos=rec.qos or "",
        node_list=rec.node_list or "",
    )


# ---- 查询作业列表 -----------------------------------------------------------

@router.get("/{user_id}", response_model=list[JobInfo])
async def list_user_jobs(user_id: str, limit: int = 10) -> list[JobInfo]:
    """查询指定用户的最近作业."""
    if limit <= 0:
        limit = 10
    try:
        client = _build_command_client()
        recs = await client.list_recent_jobs(limit=limit)
    except SSHNotConfiguredError:
        raise HTTPException(status_code=503, detail="SSH 未配置, 且降级 mock 不可用") from None
    except Exception:
        raise HTTPException(status_code=502, detail="查询作业失败") from None
    return [_to_job_info(r) for r in recs]


# ---- 诊断单个作业 -----------------------------------------------------------

@router.get("/{job_id}/diagnose", response_model=DiagnoseResponse)
async def diagnose_job(job_id: str) -> DiagnoseResponse:
    """分析作业失败原因, 返回分类 + 修复建议."""
    job_id = job_id.strip()
    if not job_id:
        raise HTTPException(status_code=422, detail="job_id 不能为空")

    try:
        client = _build_command_client()
    except SSHNotConfiguredError:
        raise HTTPException(status_code=503, detail="SSH 未配置") from None

    # 解析作业 ID(取数字部分)
    numeric = "".join(ch for ch in job_id if ch.isdigit())
    if not numeric:
        raise HTTPException(status_code=422, detail=f"无效的 job_id: {job_id}")

    # 数据来源: 是否真实配置了 SSH
    ssh_configured = bool(get_config().ssh_host and get_config().ssh_user)
    data_source = "ssh" if ssh_configured else "mock"

    try:
        rec = await client.get_job(int(numeric))
    except Exception:
        raise HTTPException(status_code=502, detail="查询作业失败") from None

    if rec is None:
        raise HTTPException(status_code=404, detail=f"作业 {job_id} 不存在")

    # 三层分析
    diag = JobDiagnoser().diagnose(rec)
    cls = ErrorClassifier().classify(rec)
    fix = FixGenerator().generate(cls)

    return DiagnoseResponse(
        job=_to_job_info(rec),
        diagnosis=DiagnoseInfo(
            is_failed=diag.is_failed,
            category=cls.category,
            subtype=cls.subtype,
            confidence=diag.confidence,
            faq_id=diag.matched_faq.id if diag.matched_faq else "",
            advice=fix.advice,
            commands=fix.commands,
            reason=diag.reason_text,
        ),
        data_source=data_source,
    )
