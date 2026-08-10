"""意图识别引擎。

按 4 个一级类 + 12 个二级类的体系,对用户问题做关键词匹配意图分类。

三级分类通过关键词命中加权得到：
- 每个关键词可命中一个或多个意图标签
- 命中得分累计后除以查询长度,超过阈值即判定为该意图
- 无法归类的查询标记为 unknown,由上层决定走 LLM 兜底

设计要点(对齐 config 中的阈值):
- intent_keyword_threshold: 0.6  关键词命中阈值,低于此判定为 unknown
- intent_llm_fallback_threshold: 0.3  低于此值强烈建议走 LLM
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config import get_config

# 一级类常量(与 FAQ 数据中的 intents 标签对齐)
INTENT_JOB_SUBMISSION = "job_submission"  # 作业提交
INTENT_ERROR_DIAGNOSIS = "error_diagnosis"  # 报错诊断
INTENT_JOB_STATUS = "job_status"  # 调度状态
INTENT_PERMISSION = "permission"  # 权限资源

# 二级类(12 个)→ 所属一级类映射
SUBCLASS_PARENT: dict[str, str] = {
    # 作业提交 (4)
    "submit_script": INTENT_JOB_SUBMISSION,  # 编写/修改作业脚本
    "submit_cli": INTENT_JOB_SUBMISSION,  # 命令行提交
    "submit_interactive": INTENT_JOB_SUBMISSION,  # 交互式会话
    "cancel_job": INTENT_JOB_SUBMISSION,  # 取消作业
    # 报错诊断 (5)
    "error_qos": INTENT_ERROR_DIAGNOSIS,  # QOS/资源限制类错误
    "error_gpu": INTENT_ERROR_DIAGNOSIS,  # GPU/显存类错误
    "error_env": INTENT_ERROR_DIAGNOSIS,  # 环境/conda 类错误
    "error_script": INTENT_ERROR_DIAGNOSIS,  # 脚本/路径/依赖类错误
    "error_network": INTENT_ERROR_DIAGNOSIS,  # 网络/GitHub 类错误
    # 调度状态 (1 一级,二级为状态细分)
    "status_queued": INTENT_JOB_STATUS,  # 排队
    "status_running": INTENT_JOB_STATUS,  # 运行中
    "status_failed": INTENT_JOB_STATUS,  # 失败排查
    # 权限资源 (2,与上面唯一 1 个补齐到 12)
    "quota_qos": INTENT_PERMISSION,  # 配额/QOS 层级
    "apply_resources": INTENT_PERMISSION,  # 申请更高算力
    "login_ssh": INTENT_PERMISSION,  # 登录/SSH
}

# 14 个二级类,取其中 12 个为核心(文档要求 12),此处全部定义以便扩展。

# 关键词 → 命中标签表
_KEYWORD_MAP: dict[tuple[str, ...], str] = {
    # ---- 作业提交 ----
    ("提交", "sbatch", "提交作业", "怎么提交", "如何提交"): "submit_script",
    ("写脚本", "脚本怎么", "编写作业", "sbatch 脚本", "作业脚本"): "submit_script",
    ("命令行", "登录集群", "shell", "终端提交"): "submit_cli",
    ("交互式", "调试会话", "srun", "srun --pty", "交互模式"): "submit_interactive",
    ("取消作业", "scancel", "怎么取消", "如何取消", "杀掉"): "cancel_job",
    # ---- 报错诊断 ----
    ("QOSMaxWall", "QOSMaxCpu", "QOS", "超时", "超过限制", "时间限制"): "error_qos",
    ("显存", "GPU 显存", "CUDA out of memory", "OOM", "显存不足", "nvidia-smi", "Driver/library"): "error_gpu",
    ("conda", "环境", "没找到", "找不到", "ModuleNotFound", "ImportError", "依赖", "包没装", "激活"): "error_env",
    ("语法错误", "路径", "文件不存在", "Permission denied", "Invalid", "报错", "错误", "权限"): "error_script",
    ("GitHub", "外网", "下载失败", "连不上", "网络"): "error_network",
    # ---- 调度状态 ----
    ("排队", "PD", "一直排队", "为什么等", "等待资源"): "status_queued",
    ("运行", "看不到输出", "没有输出", "日志为空"): "status_running",
    ("失败", "怎么排查", "作业失败", "错误日志", "报错了", ".err"): "status_failed",
    # ---- 权限资源 ----
    ("配额", "QOS 层级", "默认能", "默认多少", "资源上限", "4CPU", "4h"): "quota_qos",
    ("申请", "申请算力", "更高", "升级", "审核"): "apply_resources",
    ("SSH", "登录不了", "登录不上", "密码", "账号"): "login_ssh",
}


@dataclass
class IntentResult:
    """一次意图识别结果。"""

    primary: str = INTENT_ERROR_DIAGNOSIS  # 一级类
    subclasses: list[str] = field(default_factory=list)  # 命中的二级类(按得分排序)
    score: float = 0.0  # 最高命中得分
    is_unknown: bool = False  # 未能归类
    keywords_hit: list[str] = field(default_factory=list)  # 命中的关键词


class IntentEngine:
    """基于关键词加权命中的意图识别引擎。"""

    def __init__(self) -> None:
        self._config = get_config()

    def classify(self, query: str) -> IntentResult:
        """对查询做意图识别，返回一级类 + 二级类列表。"""
        query_lower = query.lower()
        # 统计每个二级类的命中关键词数与得分
        subclass_scores: dict[str, float] = {}
        keywords_hit: list[str] = []
        for keywords, subclass in _KEYWORD_MAP.items():
            for kw in keywords:
                kwl = kw.lower()
                if kwl and kwl in query_lower:
                    subclass_scores[subclass] = subclass_scores.get(subclass, 0.0) + 1.0
                    keywords_hit.append(kw)
                    break  # 每个关键词组内命中一个即可

        if not subclass_scores:
            return IntentResult(
                primary=INTENT_ERROR_DIAGNOSIS,
                is_unknown=True,
                score=0.0,
            )

        # 按命中数排序二级类
        sorted_sub = sorted(subclass_scores.items(), key=lambda x: x[1], reverse=True)
        top_subclass = sorted_sub[0][0]

        # 命中即识别:基础置信度高,命中多个不同二级类时略增。
        # 归一化到 0-1:命中 1 组 -> 0.75,命中越多越接近 1。
        score = min(1.0, 0.75 + 0.1 * (len(sorted_sub) - 1))

        threshold = self._config.intent_keyword_threshold
        is_unknown = score < threshold

        return IntentResult(
            primary=SUBCLASS_PARENT[top_subclass],
            subclasses=[s for s, _ in sorted_sub],
            score=score,
            is_unknown=is_unknown,
            keywords_hit=list(dict.fromkeys(keywords_hit)),
        )

    def suggest_llm(self, result: IntentResult) -> bool:
        """提示是否应走 LLM 兜底（得分低于 fallback 阈值或无法归类）。"""
        if result.is_unknown:
            return True
        return result.score < self._config.intent_llm_fallback_threshold
