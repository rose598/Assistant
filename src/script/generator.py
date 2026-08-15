"""脚本生成器（第 5 周，模板渲染）。

从模板 + 覆盖参数渲染 sbatch 脚本。渲染顺序与指令格式（短选项空格分隔、
长选项等号连接）严格按验收契约，任何格式变化都会破坏子串断言。

契约来源：docs/week5-A-state-machine-design.md §五
（test_script_parse_generate.py 的 TestScriptGenerator /
TestScriptTemplateCombinations / TestScriptValidation，共 25 用例）。
"""

from __future__ import annotations

from src.script.templates import TEMPLATES


class ScriptGenerator:
    """模板脚本生成器：模板默认值 + 覆盖参数 → sbatch 脚本文本。"""

    def generate(self, template_name: str, overrides: dict[str, str] | None = None) -> str:
        """根据模板生成脚本。

        Args:
            template_name: 模板名（TEMPLATES 中的 5 种之一）。
            overrides: 需覆盖的参数（合并到模板默认值之上）。

        Returns:
            生成的脚本内容。

        Raises:
            ValueError: 模板名不存在。
        """
        template = TEMPLATES.get(template_name)
        if template is None:
            raise ValueError(f"Unknown template: {template_name}")

        params = template.defaults.copy()
        if overrides:
            params.update(overrides)

        # 渲染顺序固定：与验收用例的子串断言一一对应
        lines = ["#!/bin/bash"]
        if "job_name" in params:
            lines.append(f"#SBATCH -J {params['job_name']}")
        if "partition" in params:
            lines.append(f"#SBATCH -p {params['partition']}")
        if "qos" in params:
            lines.append(f"#SBATCH --qos={params['qos']}")
        if "gres" in params:
            lines.append(f"#SBATCH --gres={params['gres']}")
        if "cpus" in params:
            lines.append(f"#SBATCH -c {params['cpus']}")
        if "mem" in params:
            lines.append(f"#SBATCH --mem={params['mem']}")
        if "time" in params:
            lines.append(f"#SBATCH -t {params['time']}")

        lines.append("")
        lines.append("# Your commands here")

        return "\n".join(lines)


__all__ = ["ScriptGenerator"]
