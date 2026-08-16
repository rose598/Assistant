"""脚本解析与生成测试.

测试 5 个模板 × 3 种参数组合 = 15 个用例.
"""

from __future__ import annotations

import pytest

from src.script.generator import ScriptGenerator
from src.script.parser import SbatchParser
from src.script.templates import TEMPLATES

# ── 测试参数组合 ──
PARAM_COMBINATIONS: list[dict[str, str]] = [
    # 组合 1: 默认参数
    {},
    # 组合 2: 修改分区
    {"partition": "GPU-RTX5090"},
    # 组合 3: 修改时间和内存
    {"time": "02:00:00", "mem": "8G"},
]


class TestScriptParser:
    """脚本解析器测试."""

    @pytest.fixture
    def parser(self) -> SbatchParser:
        """返回脚本解析器."""
        return SbatchParser()

    def test_parse_empty_script(self, parser: SbatchParser) -> None:
        """测试解析空脚本."""
        result = parser.parse("")
        assert result == {}

    def test_parse_no_sbatch(self, parser: SbatchParser) -> None:
        """测试解析无 SBATCH 的脚本."""
        script = "#!/bin/bash\necho hello"
        result = parser.parse(script)
        assert result == {}

    def test_parse_key_value_format(self, parser: SbatchParser) -> None:
        """测试解析 --key=value 格式."""
        script = "#SBATCH --partition=Students\n#SBATCH --qos=qos_stu_default"
        result = parser.parse(script)
        assert result["partition"] == "Students"
        assert result["qos"] == "qos_stu_default"

    def test_parse_short_key_format(self, parser: SbatchParser) -> None:
        """测试解析 -k value 格式."""
        script = "#SBATCH -p Students\n#SBATCH -c 4"
        result = parser.parse(script)
        assert result["p"] == "Students"
        assert result["c"] == "4"

    def test_parse_gres_format(self, parser: SbatchParser) -> None:
        """测试解析 GRES 格式."""
        script = "#SBATCH --gres=gpu:2"
        result = parser.parse(script)
        assert result["gres"] == "gpu:2"

    def test_parse_time_format(self, parser: SbatchParser) -> None:
        """测试解析时间格式."""
        script = "#SBATCH -t 04:00:00"
        result = parser.parse(script)
        assert result["t"] == "04:00:00"

    def test_parse_multiple_directives(self, parser: SbatchParser) -> None:
        """测试解析多个指令."""
        script = """#!/bin/bash
#SBATCH -J my_job
#SBATCH -p Students
#SBATCH --qos=qos_stu_default
#SBATCH --gres=gpu:1
#SBATCH -c 4
#SBATCH --mem=16G
#SBATCH -t 04:00:00

echo "Hello"
"""
        result = parser.parse(script)
        assert result["J"] == "my_job"
        assert result["p"] == "Students"
        assert result["qos"] == "qos_stu_default"
        assert result["gres"] == "gpu:1"
        assert result["c"] == "4"
        assert result["mem"] == "16G"
        assert result["t"] == "04:00:00"


class TestScriptGenerator:
    """脚本生成器测试."""

    @pytest.fixture
    def generator(self) -> ScriptGenerator:
        """返回脚本生成器."""
        return ScriptGenerator()

    def test_generate_minimal_cpu(self, generator: ScriptGenerator) -> None:
        """测试生成最小 CPU 脚本."""
        script = generator.generate("minimal_cpu")
        assert "#!/bin/bash" in script
        assert "-p Students" in script
        assert "-c 1" in script

    def test_generate_gpu_single(self, generator: ScriptGenerator) -> None:
        """测试生成单卡 GPU 脚本."""
        script = generator.generate("gpu_single")
        assert "--gres=gpu:1" in script
        assert "--qos=qos_stu_default" in script

    def test_generate_gpu_multi(self, generator: ScriptGenerator) -> None:
        """测试生成多卡 GPU 脚本."""
        script = generator.generate("gpu_multi")
        assert "--gres=gpu:2" in script
        assert "--qos=qos_stu_medium_2gpu" in script

    def test_generate_cpu_long(self, generator: ScriptGenerator) -> None:
        """测试生成长时间 CPU 脚本."""
        script = generator.generate("cpu_long")
        assert "--qos=qos_stu_cpu_long" in script
        assert "-t 72:00:00" in script

    def test_generate_debug_interactive(self, generator: ScriptGenerator) -> None:
        """测试生成交互式调试脚本."""
        script = generator.generate("debug_interactive")
        assert "-p Students" in script

    def test_generate_unknown_template(self, generator: ScriptGenerator) -> None:
        """测试生成未知模板抛出异常."""
        with pytest.raises(ValueError, match="Unknown template"):
            generator.generate("nonexistent")

    def test_generate_with_overrides(self, generator: ScriptGenerator) -> None:
        """测试生成带覆盖参数的脚本."""
        script = generator.generate("gpu_single", {"partition": "GPU-RTX5090"})
        assert "-p GPU-RTX5090" in script


class TestScriptTemplateCombinations:
    """脚本模板参数组合测试（5模板 × 3组合 = 15用例）."""

    @pytest.fixture
    def generator(self) -> ScriptGenerator:
        """返回脚本生成器."""
        return ScriptGenerator()

    @pytest.mark.parametrize("template_name", list(TEMPLATES.keys()))
    @pytest.mark.parametrize("params", PARAM_COMBINATIONS, ids=["default", "partition", "time_mem"])
    def test_template_combination(
        self, generator: ScriptGenerator, template_name: str, params: dict[str, str]
    ) -> None:
        """测试模板参数组合."""
        script = generator.generate(template_name, params if params else None)

        # 验证脚本格式
        assert "#!/bin/bash" in script

        # 验证覆盖参数生效
        for key, value in params.items():
            if key == "partition":
                assert f"-p {value}" in script
            elif key == "time":
                assert f"-t {value}" in script
            elif key == "mem":
                assert f"--mem={value}" in script


class TestScriptValidation:
    """脚本验证测试."""

    @pytest.fixture
    def generator(self) -> ScriptGenerator:
        """返回脚本生成器."""
        return ScriptGenerator()

    def test_valid_partition_qos_match(self, generator: ScriptGenerator) -> None:
        """测试有效的分区与 QOS 匹配."""
        script = generator.generate("gpu_single")
        # Students 分区与 qos_stu_default 匹配
        assert "-p Students" in script
        assert "--qos=qos_stu_default" in script

    def test_resource_within_qos_limit(self, generator: ScriptGenerator) -> None:
        """测试资源在 QOS 限制内."""
        script = generator.generate("gpu_single")
        # 默认配置：4CPU, 1GPU, 4h
        assert "-c 4" in script
        assert "--gres=gpu:1" in script
        assert "-t 04:00:00" in script

    def test_syntax_valid(self, generator: ScriptGenerator) -> None:
        """测试脚本语法有效."""
        script = generator.generate("gpu_single")
        # 验证没有语法错误
        assert "#SBATCH" in script
        # 验证没有非法字符
        assert "\x00" not in script
