"""脚本一键导出（第 5 周，A 职责）。

改写完成后把最终脚本整理为可下载的 sbatch 文件：规范化内容
（结尾换行幂等）、生成安全文件名、打包下载响应元数据。

本模块无 D 预置验收用例（plan 交付物"一键导出"，验收口径
"可导出可用"），自带单测见 tests/test_script/test_exporter.py。
"""

from __future__ import annotations

import re

# 文件名允许字符：字母数字与 ._-，其余替换为下划线
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]")
_DEFAULT_STEM = "job"
_EXTENSION = ".sbatch"
_MEDIA_TYPE = "text/plain"


class ScriptExporter:
    """脚本导出器：内容规范化 + 文件名生成 + 下载响应打包。"""

    def normalize(self, script: str) -> str:
        """保证脚本以单个换行结尾（幂等）；空串原样返回。

        Args:
            script: 脚本内容。

        Returns:
            规范化后的脚本内容。
        """
        if not script:
            return ""
        return script if script.endswith("\n") else script + "\n"

    def suggest_filename(self, job_name: str = "") -> str:
        """按作业名生成安全文件名。

        Args:
            job_name: 作业名（可为空）。

        Returns:
            ``<净化后作业名>.sbatch``；作业名为空或净化后为空
            时用默认名 ``job.sbatch``。
        """
        stem = _FILENAME_SAFE.sub("_", job_name.strip()).strip("_")
        if not stem:
            stem = _DEFAULT_STEM
        return f"{stem}{_EXTENSION}"

    def build_response(
        self, script: str, job_name: str = "", filename: str | None = None
    ) -> dict[str, str]:
        """打包下载响应元数据。

        Args:
            script: 脚本内容。
            job_name: 作业名（用于建议文件名）。
            filename: 显式指定的文件名（优先于建议名）。

        Returns:
            含 ``filename`` / ``content`` / ``media_type`` 的字典。
        """
        return {
            "filename": filename or self.suggest_filename(job_name),
            "content": self.normalize(script),
            "media_type": _MEDIA_TYPE,
        }


__all__ = ["ScriptExporter"]
