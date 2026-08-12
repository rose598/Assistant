"""Prompt 模板体系。

第 3 周周一交付物：系统提示词 / RAG 增强 / 脚本生成 / 日志分析 4 类模板。
每类提供默认版本，后续可基于 A/B 测试迭代为 v2。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

system_prompt = """你是中国科学技术大学 107 算力平台的智能助手。
你的职责是帮助本科生解答关于 Slurm 作业调度、GPU 使用、环境配置等问题。
只回答与 107 算力平台相关的问题；基于知识库回答，不编造信息。
回答要简洁，使用中文，适当使用列表和代码块。
"""


@dataclass
class PromptTemplate:
    """一个可渲染的 Prompt 模板。"""

    name: str
    system: str
    template: str
    version: str = "v1"

    def render(self, **kwargs: Any) -> list[dict[str, str]]:
        """渲染为 OpenAI messages 格式。

        同时格式化 system 与 user 模板（二者都可能含 ``{placeholder}``，
        如 RAG 模板在 system 里注入 ``{knowledge}``）。
        """
        system = self.system.format(**kwargs)
        content = self.template.format(**kwargs)
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ]


# ---- 基础问答 —— 无知识库 ----
BASIC_TEMPLATE = PromptTemplate(
    name="basic",
    system=system_prompt,
    template="用户问题：\n{question}\n",
)

# ---- RAG 增强问答 ----
RAG_TEMPLATE = PromptTemplate(
    name="rag",
    system=system_prompt
    + "\n## 知识参考\n请基于以下检索到的知识回答：\n{knowledge}\n",
    template="用户问题：\n{question}\n",
)

# ---- 脚本生成 ----
SCRIPT_GENERATE_TEMPLATE = PromptTemplate(
    name="script_generate",
    system=system_prompt
    + "\n你会根据用户描述生成可直接提交的 sbatch 脚本，字段含 -p、--qos、--gres、-c、--mem、-t。",
    template=(
        "请为以下任务生成 sbatch 脚本：\n{description}\n\n"
        "可用分区：{partitions}\n可用 QOS：{qos_list}\n"
        "请只输出脚本本身（含 #SBATCH 注释行），并附带一行简短说明。"
    ),
)

# ---- 日志分析 ----
LOG_ANALYSIS_TEMPLATE = PromptTemplate(
    name="log_analysis",
    system=system_prompt
    + "\n你会根据作业状态、Reason 字段和错误日志判断失败原因并给出修复建议。",
    template=(
        "作业诊断信息：\n"
        "- 作业号(JOBID)：{job_id}\n"
        "- 状态(State)：{job_state}\n"
        "- Reason：{reason}\n"
        "- 错误日志摘要：\n{error_log}\n\n"
        "请判断失败原因类别并给出可执行的修复步骤。"
    ),
)

_ALL_TEMPLATES: dict[str, PromptTemplate] = {
    "basic": BASIC_TEMPLATE,
    "rag": RAG_TEMPLATE,
    "script_generate": SCRIPT_GENERATE_TEMPLATE,
    "log_analysis": LOG_ANALYSIS_TEMPLATE,
}


def get_template(name: str) -> PromptTemplate:
    """按名称获取模板；未知名称时回退到 basic。"""
    return _ALL_TEMPLATES.get(name, BASIC_TEMPLATE)


def list_templates() -> list[str]:
    """列出所有模板名。"""
    return list(_ALL_TEMPLATES.keys())
