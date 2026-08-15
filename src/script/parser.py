"""Slurm sbatch 脚本解析器（第 5 周，A 职责）。

从 sbatch 脚本中提取 ``#SBATCH`` 指令字段，为对话式改写与字段建议提供数据。

契约来源：docs/week5-A-state-machine-design.md §四
（test_script_parse_generate.py 的 TestScriptParser，7 用例）：
- 支持 ``--key=value`` 与 ``-k value`` 两种格式；
- 短选项保留原始键名，**不做别名映射**（``-p`` 解析为 ``"p"`` 而非 ``"partition"``）；
- 空脚本 / 无 #SBATCH 行 → 返回空 dict。
"""

from __future__ import annotations

import re

_SBATCH_PATTERN = re.compile(r"#SBATCH\s+(.+)")


class SbatchParser:
    """sbatch 脚本解析器：正则提取 #SBATCH 指令字段。"""

    def parse(self, script_content: str) -> dict[str, str]:
        """解析 sbatch 脚本，返回指令字段字典。

        Args:
            script_content: 脚本内容。

        Returns:
            指令字段字典（键为去掉前导短横线的选项名，值为字符串）；
            空脚本或无 #SBATCH 指令时返回 ``{}``。
        """
        result: dict[str, str] = {}
        for match in _SBATCH_PATTERN.finditer(script_content):
            line = match.group(1).strip()
            # --key=value 格式
            if "=" in line:
                key, _, value = line.partition("=")
                result[key.lstrip("-").strip()] = value.strip()
            # -k value 格式
            else:
                parts = line.split()
                if len(parts) >= 2:
                    result[parts[0].lstrip("-")] = parts[1]
        return result


__all__ = ["SbatchParser"]
