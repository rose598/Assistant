"""错误修复建议生成器。

根据错误分类 (ErrorClassification) 生成可执行的修复建议:
- 每个子类预定义修复模板, 含可插入的作业信息占位(作业 ID、分区、QOS、日志)
- 输出 FixSuggestion: 建议正文 + 可直接执行的命令列表
- 同时尝试匹配知识库 FAQ 答案(当分类对应明确 FAQ 时)

设计要点(鲁棒性):
- 未知子类 -> 通用修复模板(multi-category 兜底), 不抛异常。
- 作业信息缺失(无 job_id / 无日志名) -> 优雅降级, 跳过对应占位, 不报错。
- 模板填充使用安全格式化: 只替换已知占位, 不信任外部注入格式串。
- 输出结构化 FixSuggestion, 供 API 序列化与前端展示。

典型用法::

    fix = FixGenerator()
    suggestion = fix.generate(classification)
    print(suggestion.advice)
    for cmd in suggestion.commands: print("$ " + cmd)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.knowledge.loader import KnowledgeLoader, KnowledgeMatcher
from src.log_analysis.classifier import ErrorClassification
from src.log_analysis.commands import JobRecord


@dataclass
class FixSuggestion:
    """一次修复建议的结果。"""

    subtype: str
    label: str  # 人类可读类别
    advice: str  # 建议正文
    commands: list[str] = field(default_factory=list)  # 可执行命令
    faq_answer: str = ""  # 匹配到的知识库 FAQ 答案(可为空)


# 每个子类的修复模板: (建议正文, 命令列表模板)
# 占位符: {job_id} {partition} {qos} {log_file}
_TEMPLATES: dict[str, tuple[str, list[str]]] = {
    "gpu_oom": (
        "检测到 GPU 显存不足(OOM)。优先尝试减小 batch size / 模型规模 / 数据加载并发,"
        "确认代码真正使用了 GPU(而非 CPU 模式)。",
        ["nvidia-smi", "squeue -u $USER"],
    ),
    "mem_oom": (
        "检测到系统内存不足(OOM)。请降低 --mem 需求或减少数据加载并发; 确认作业未在"
        "登录节点运行重计算任务。",
        ["squeue -u $USER", "free -h"],
    ),
    "disk_full": (
        "检测到磁盘空间不足。请清理作业目录 / 共享存储中的大文件与缓存, 或申请更大的"
        "存储空间; 确认写入路径所在文件系统剩余空间充足。",
        ["df -h", "du -sh {log_file} 2>/dev/null || true"],
    ),
    "syntax_error": (
        "检测到脚本语法错误。请检查提交脚本的语法与缩进, 可用 bash -n 做静态检查。",
        ["bash -n {log_file} 2>/dev/null || echo '检查脚本语法'"],
    ),
    "path_error": (
        "检测到路径或文件不存在。请核对脚本、数据与日志中的路径是否真实存在。",
        [
            "ls -l {log_file}",
            "pwd",
        ],
    ),
    "dependency_error": (
        "检测到依赖缺失或导入失败。请确认所需 Python 模块已安装, 且运行环境已激活。",
        [
            "conda activate your_env",
            "python -c \"import your_module; print('ok')\"",
        ],
    ),
    "conda_missing": (
        "检测到 conda 环境未激活。批处理脚本中需先初始化并激活 conda 环境。",
        ["conda activate your_env", "which python"],
    ),
    "module_missing": (
        "检测到 Python 模块未安装。请安装报错中提到的模块后再提交。",
        ["pip install <module_name>  # 替换为实际缺失模块"],
    ),
    "cuda_mismatch": (
        "检测到 CUDA / 驱动版本不匹配。请确认申请到 GPU 的节点驱动与 CUDA 兼容,"
        "检查 nvidia-smi 与编译配置。",
        ["nvidia-smi", "python -c \"import torch; print(torch.cuda.is_available())\""],
    ),
    "kernel_issue": (
        "检测到内核 / 指令集兼容问题(如 Illegal instruction 或 GLIBCXX 版本过低)。"
        "请检查作业所用程序的编译环境与运行节点的 gcc/glibc/CUDA 版本是否一致。",
        ["gcc --version", "ldd --version", "cat /etc/os-release"],
    ),
    "qos_limit": (
        "检测到 QOS / 资源配额超限。请调整作业运行的资源申请(sbatch 的 -p/--qos/"
        "--gres/-t 字段), 控制在当前 QOS 允许范围内; 需要更多资源时走平台申请。",
        [
            "scontrol show partition {partition}",
            "squeue -u $USER",
        ],
    ),
    "permission_denied": (
        "检测到文件或目录权限不足。请检查脚本、数据和输出路径的读/写/执行权限。",
        ["ls -l {log_file}", "chmod +x your_script.sbatch 2>/dev/null || true"],
    ),
}

# 未知子类的通用模板
_GENERIC_TEMPLATE: tuple[str, list[str]] = (
    "未能精确归类错误原因, 建议按通用流程排查: 查看日志尾部、确认资源申请、"
    "核对路径与权限。也可将完整错误信息和作业 ID 提供给平台管理员。",
    ["squeue -u $USER", "tail -n 80 {log_file}"],
)


class FixGenerator:
    """根据错误分类生成修复建议。"""

    def __init__(self) -> None:
        # 懒加载知识库匹配器(仅当需要 FAQ 增强时)
        self._matcher: KnowledgeMatcher | None = None

    def generate(self, cls: ErrorClassification) -> FixSuggestion:
        """生成修复建议。"""
        subtype = cls.subtype
        label = cls.label  # 未知子类时也会有合理兜底标签
        record = cls.record

        # 1. 选模板(未知子类用通用模板)
        advice_tmpl, cmds_tmpl = _TEMPLATES.get(subtype, _GENERIC_TEMPLATE)

        # 2. 生成日志文件名占位(若作业有 JobName 或日志惯例)
        log_file = self._make_log_hint(record)

        # 3. 填充占位(仅替换已知字段, 安全)
        ctx = {
            "job_id": record.job_id or "<作业ID>",
            "partition": record.partition or "<分区>",
            "qos": record.qos or "<QOS>",
            "log_file": log_file,
        }
        advice = advice_tmpl
        commands = [self._fill(c, ctx) for c in cmds_tmpl]

        # 4. 尝试附加 FAQ 答案增强
        faq_answer = self._lookup_faq(record, cls)

        return FixSuggestion(
            subtype=subtype,
            label=label,
            advice=advice,
            commands=commands,
            faq_answer=faq_answer,
        )

    # -- 内部 --
    @staticmethod
    def _make_log_hint(record: JobRecord) -> str:
        """生成日志文件占位(基于 JobName 的常见 -o/-e 命名)。"""
        if record.job_name:
            return f"{record.job_name}.err"
        return "<日志文件>"

    @staticmethod
    def _fill(text: str, ctx: dict[str, str]) -> str:
        """用上下文替换 {占位}, 未知占位保留原样。"""
        for key, val in ctx.items():
            text = text.replace("{" + key + "}", val)
        return text

    def _lookup_faq(self, record: JobRecord, cls: ErrorClassification) -> str:
        """用错误分类 + 记录查询知识库 FAQ, 返回答案(空表示未命中)。"""
        try:
            if self._matcher is None:
                loader = KnowledgeLoader()
                kb = loader.load()
                self._matcher = KnowledgeMatcher(kb)
            # 用子类标签 + reason 组成查询串
            query_parts = [cls.label, record.reason or "", record.job_name or ""]
            query = " ".join(p for p in query_parts if p).strip()
            if not query:
                return ""
            matches = self._matcher.match(query, top_k=1)
            if matches:
                return matches[0][0].answer
            return ""
        except Exception:
            return ""


__all__ = ["FixGenerator", "FixSuggestion"]
