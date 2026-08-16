"""脚本模板定义（第 5 周，A/B 共享）。

5 个预设模板对应 107 算力平台的典型作业形态；参数默认值与真实平台
口径一致（Students 分区、qos_stu_default / qos_stu_medium_2gpu /
qos_stu_cpu_long 等）。

契约来源：docs/week5-A-state-machine-design.md §五
（test_script_parse_generate.py 的 TEMPLATES 定义，逐值对齐）。
``ScriptTemplate`` 为 project_plan.md:260 约定的 A/B 共享定义，
B 侧后续模板/验证工作直接复用本文件。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScriptTemplate:
    """脚本模板：名称 + 描述 + 参数默认值。"""

    name: str
    description: str
    defaults: dict[str, str]


TEMPLATES: dict[str, ScriptTemplate] = {
    "minimal_cpu": ScriptTemplate(
        name="minimal_cpu",
        description="简单 CPU 计算",
        defaults={
            "partition": "Students",
            "cpus": "1",
            "mem": "4G",
            "time": "00:10:00",
        },
    ),
    "gpu_single": ScriptTemplate(
        name="gpu_single",
        description="单卡 GPU 训练",
        defaults={
            "partition": "Students",
            "qos": "qos_stu_default",
            "gres": "gpu:1",
            "cpus": "4",
            "mem": "16G",
            "time": "04:00:00",
        },
    ),
    "gpu_multi": ScriptTemplate(
        name="gpu_multi",
        description="多卡 GPU 训练",
        defaults={
            "partition": "Students",
            "qos": "qos_stu_medium_2gpu",
            "gres": "gpu:2",
            "cpus": "8",
            "mem": "32G",
            "time": "12:00:00",
        },
    ),
    "cpu_long": ScriptTemplate(
        name="cpu_long",
        description="长时间 CPU 计算",
        defaults={
            "partition": "Students",
            "qos": "qos_stu_cpu_long",
            "cpus": "8",
            "mem": "32G",
            "time": "72:00:00",
        },
    ),
    "debug_interactive": ScriptTemplate(
        name="debug_interactive",
        description="交互式调试",
        defaults={
            "partition": "Students",
            "qos": "qos_stu_default",
            "gres": "gpu:1",
            "cpus": "1",
            "time": "00:10:00",
        },
    ),
}


__all__ = ["ScriptTemplate", "TEMPLATES"]
