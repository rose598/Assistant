"""一键修复命令生成模块.

第 4 周 A 交付物（plan §第4周周四 / 进度记录 §七）：根据诊断分类结果
（``ErrorClassification``）生成**可直接粘贴执行的修复命令**（sbatch/pip/conda/
scontrol/chmod 等）。

与 [fix_generator.py](../log_analysis/fix_generator.py) 的关系（单向只读复用，不碰 B 文件）：
- ``FixGenerator`` 产物是"建议文本 + 诊断辅助命令"；本模块把产物理念**收敛为
  可执行的修复动作命令**（主命令 + 辅助命令）。
- 复用其 ``ErrorClassification`` 输入契约与 advice 文本（失败不影响本模块，兜底内置文案）。

设计要点：
- **12 子类逐一命令模板**：占位符 ``{job_id}``/``{workdir}``/``{script}``/
  ``{partition}``/``{qos}`` 用 ``JobRecord`` 真实信息填充；缺失字段用 ``<...>``
  可见占位（命令仍保持合法 shell 形态）。
- **unknown 兜底**：返回空命令 + 提示文案，不抛异常。
- **只产出命令字符串，不真实执行**（不引入任何真实副作用）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.log_analysis.classifier import SUBTYPE_CATEGORY, ErrorClassification
from src.log_analysis.fix_generator import FixGenerator

__all__ = ["AutoFixCmd", "AutoFixResult", "CMD_TEMPLATES"]


@dataclass
class AutoFixResult:
    """一次一键修复命令生成的结果。"""

    subtype: str
    label: str
    command: str = ""  # 主修复命令（unknown 时为空字符串）
    commands: list[str] = field(default_factory=list)  # 主命令 + 辅助命令全列表
    note: str = ""  # 使用说明 / 兜底提示文案

    @property
    def has_command(self) -> bool:
        """是否产出了可执行命令。"""
        return bool(self.command)


# 每个子类的修复命令模板：(主命令, [辅助命令], 使用说明)
# 占位符：{job_id} {workdir} {script} {partition} {qos}
CMD_TEMPLATES: dict[str, tuple[str, list[str], str]] = {
    "gpu_oom": (
        "cd {workdir} && sbatch {script}",
        ["nvidia-smi"],
        "先减小 batch size / 模型规模（编辑脚本后），再用此命令重新提交；"
        "nvidia-smi 可确认显存规格。",
    ),
    "mem_oom": (
        "cd {workdir} && sbatch {script}",
        ["scontrol show job {job_id}"],
        "先在脚本中降低 --mem 请求或减少数据加载并发，再重新提交；"
        "避免在登录节点跑重计算。",
    ),
    "disk_full": (
        "du -sh ~/* 2>/dev/null | sort -h | tail -n 20",
        ["df -h"],
        "先用该命令定位家目录占用最大的目录并清理（缓存/输出/数据集），"
        "df -h 确认文件系统余量后重新提交。",
    ),
    "syntax_error": (
        "bash -n {script}",
        ["cd {workdir} && sbatch {script}"],
        "bash -n 静态检查脚本语法（不执行）；修正后运行第二条重新提交。",
    ),
    "path_error": (
        "ls -l {workdir}",
        ["cd {workdir} && sbatch {script}"],
        "核对脚本中引用的路径真实存在（注意作业在计算节点运行，"
        "需使用共享存储上的绝对路径）；修正后重新提交。",
    ),
    "dependency_error": (
        "pip install <缺失的模块名>",
        ["cd {workdir} && sbatch {script}"],
        "把命令中的占位替换为报错提到的模块名；安装成功后重新提交。",
    ),
    "conda_missing": (
        "conda activate <环境名>",
        ["which python", "cd {workdir} && sbatch {script}"],
        "批处理脚本开头需先初始化并激活 conda 环境（如 source "
        "~/miniconda3/etc/profile.d/conda.sh && conda activate <环境名>）；"
        "先交互式验证环境，再重新提交。",
    ),
    "module_missing": (
        "pip install <缺失的模块名>",
        ["python -c \"import sys; print(sys.executable)\""],
        "替换为报错提到的模块名；注意安装到作业实际使用的 Python 环境"
        "（第二条命令可确认当前解释器）。",
    ),
    "cuda_mismatch": (
        "nvidia-smi",
        ["python -c \"import torch; print(torch.version.cuda, torch.cuda.is_available())\""],
        "核对节点驱动版本与代码所用 CUDA 版本是否兼容；必要时改用匹配版本的"
        "框架（如 pip 指定 cuda 版本的 torch）后重新提交。",
    ),
    "kernel_issue": (
        "gcc --version && ldd --version",
        ["cat /etc/os-release"],
        "检查编译环境与运行节点的 gcc/glibc 版本一致性；本地编译的程序"
        "建议在与平台一致的环境中重新编译，或联系管理员。",
    ),
    "qos_limit": (
        "sacctmgr show qos",
        ["squeue -u $USER", "cd {workdir} && sbatch {script}"],
        "先查看当前授权的 QOS 及其上限；把脚本中 -t/--gres/--mem 调整到"
        "QOS 允许范围内（或走平台资源申请提升 QOS）后重新提交。",
    ),
    "permission_denied": (
        "chmod +x {script}",
        ["ls -l {script}"],
        "为提交脚本添加执行权限；若为数据文件权限问题，按 ls -l 输出对"
        "相应文件 chmod。",
    ),
}

# unknown 兜底提示文案
_UNKNOWN_NOTE = (
    "未能精确归类错误原因，暂无可直接执行的修复命令。建议：查看作业日志尾部"
    "（tail -n 80 <日志文件>）、核对资源申请与路径权限；或将完整错误信息与"
    "作业 ID 提供给平台管理员。"
)


class AutoFixCmd:
    """一键修复命令生成器。

    ``fix_generator``：可选注入（测试/替换用）；缺省内部构造 ``FixGenerator``，
    用于补充其 advice 文本（失败兜底，不影响命令生成）。
    """

    def __init__(self, fix_generator: FixGenerator | None = None) -> None:
        self._fix_generator = fix_generator

    def generate(self, cls: ErrorClassification) -> AutoFixResult:
        """按分类结果生成一键修复命令；unknown/未覆盖子类兜底为空命令 + 提示。"""
        record = cls.record
        ctx = {
            "job_id": record.job_id or "<作业ID>",
            "workdir": record.workdir or "<工作目录>",
            "script": record.command or "<提交脚本>",
            "partition": record.partition or "<分区>",
            "qos": record.qos or "<QOS>",
        }

        template = CMD_TEMPLATES.get(cls.subtype)
        if template is None:
            return AutoFixResult(
                subtype=cls.subtype,
                label=cls.label,
                command="",
                commands=[],
                note=self._fallback_note(cls),
            )

        main_tmpl, aux_tmpls, note = template
        command = _fill(main_tmpl, ctx)
        commands = [command] + [_fill(c, ctx) for c in aux_tmpls]
        return AutoFixResult(
            subtype=cls.subtype,
            label=cls.label,
            command=command,
            commands=commands,
            note=note,
        )

    def _fallback_note(self, cls: ErrorClassification) -> str:
        """unknown 兜底文案：优先附加 FixGenerator 的建议（失败不抛）。"""
        extra = ""
        try:
            fg = self._fix_generator or FixGenerator()
            suggestion = fg.generate(cls)
            if suggestion.advice:
                extra = f"（修复建议参考：{suggestion.advice}）"
        except Exception:
            extra = ""
        return _UNKNOWN_NOTE + extra


def _fill(text: str, ctx: dict[str, str]) -> str:
    """安全占位替换：只替换已知 key，未知占位保留原样。"""
    for key, val in ctx.items():
        text = text.replace("{" + key + "}", val)
    return text


# 模板覆盖性自检（导入期不执行，供测试引用）
KNOWN_SUBTYPES: frozenset[str] = frozenset(SUBTYPE_CATEGORY)
MISSING_TEMPLATES: frozenset[str] = KNOWN_SUBTYPES - frozenset(CMD_TEMPLATES)
