"""脚本导出器自测（第 5 周，A 侧；无 D 预置用例，验收口径"可导出可用"）."""

from __future__ import annotations

import re

from src.script.exporter import ScriptExporter


class TestScriptExporter:
    """内容规范化 / 文件名生成 / 响应打包."""

    def setup_method(self) -> None:
        self.exporter = ScriptExporter()

    def test_normalize_appends_newline(self) -> None:
        """缺尾换行时补齐."""
        assert self.exporter.normalize("#!/bin/bash\necho hi") == "#!/bin/bash\necho hi\n"

    def test_normalize_idempotent(self) -> None:
        """已有尾换行时不重复添加."""
        script = "#!/bin/bash\necho hi\n"
        assert self.exporter.normalize(script) == script
        assert self.exporter.normalize(self.exporter.normalize(script)) == script

    def test_normalize_empty(self) -> None:
        """空串原样返回."""
        assert self.exporter.normalize("") == ""

    def test_filename_from_job_name(self) -> None:
        """正常作业名直接加扩展名."""
        assert self.exporter.suggest_filename("train_job") == "train_job.sbatch"

    def test_filename_sanitized(self) -> None:
        """非法字符替换为下划线."""
        filename = self.exporter.suggest_filename("my job/v2")
        assert filename.endswith(".sbatch")
        assert re.fullmatch(r"[A-Za-z0-9._-]+", filename)
        assert " " not in filename
        assert "/" not in filename

    def test_filename_fallback(self) -> None:
        """空作业名或净化后为空时用默认名."""
        assert self.exporter.suggest_filename("") == "job.sbatch"
        assert self.exporter.suggest_filename("   ") == "job.sbatch"
        assert self.exporter.suggest_filename("///") == "job.sbatch"

    def test_build_response_structure(self) -> None:
        """响应含三键，内容已规范化."""
        response = self.exporter.build_response("#!/bin/bash\necho hi", job_name="demo")
        assert response["filename"] == "demo.sbatch"
        assert response["content"] == "#!/bin/bash\necho hi\n"
        assert response["media_type"] == "text/plain"

    def test_build_response_explicit_filename(self) -> None:
        """显式文件名优先于建议名."""
        response = self.exporter.build_response("x\n", job_name="demo", filename="custom.sh")
        assert response["filename"] == "custom.sh"
