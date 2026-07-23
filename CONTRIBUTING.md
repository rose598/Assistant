# 贡献指南

感谢参与 107-Agent 项目开发！本文档将指导你如何进行代码贡献。

## 开发环境搭建

### 1. 克隆与安装

```bash
git clone <repo-url>
cd 107-agent

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 安装开发依赖
pip install -e ".[dev]"

# 安装 pre-commit hooks
pre-commit install
```

### 2. 验证环境

```bash
# 检查代码规范
ruff check src/ tests/

# 检查类型标注
mypy src/ --ignore-missing-imports

# 运行测试
pytest
```

## 代码规范

### Python 代码风格

- 遵循 **PEP 8** 规范
- 使用 **ruff** 进行代码检查和格式化
- 行宽限制：100 字符
- 使用双引号 `"` 作为字符串定界符

### 类型标注

- 使用 **mypy strict** 模式
- 所有函数参数和返回值必须标注类型
- 使用 `from __future__ import annotations` 启用延迟类型求值

```python
# 正确示例
from __future__ import annotations

def greet(name: str, greeting: str = "你好") -> str:
    """向用户问好."""
    return f"{greeting}, {name}!"
```

### 文档字符串

所有函数、类、模块必须有 docstring，使用中文说明：

```python
def process_query(query: str) -> dict[str, Any]:
    """处理用户查询请求.

    Args:
        query: 用户输入的自然语言问题.

    Returns:
        包含回答内容和置信度的字典:
        - answer: 回答文本
        - confidence: 置信度 (0.0-1.0)
        - sources: 引用的知识库来源列表

    Raises:
        ValueError: 当 query 为空字符串时.
    """
    ...
```

### 代码长度限制

- 函数体 ≤ 50 行
- 类定义 ≤ 300 行
- 超过限制请拆分为更小的函数/类

### 异常处理

- 不允许 `except: pass`
- 必须指定具体异常类型
- 使用自定义异常类处理业务错误

```python
# 错误示例
try:
    process(data)
except:
    pass

# 正确示例
try:
    process(data)
except ValueError as e:
    logger.error(f"数据格式错误: {e}")
    raise ProcessingError(f"无法处理数据: {e}") from e
```

### 配置管理

- 不允许硬编码路径、密码、URL
- 统一使用 `src/config.py` 管理配置
- 敏感信息通过环境变量或 `.env` 文件配置

## Git 规范

### Commit Message 格式

格式：`[module] description`

模块名称使用小写，与目录名一致：

| 模块 | 示例 |
|------|------|
| knowledge | `[knowledge] add faq loader` |
| intent | `[intent] implement keyword matcher` |
| log_analysis | `[log_analysis] fix ssh timeout` |
| llm | `[llm] add rag engine` |
| monitor | `[monitor] implement queue alert` |
| dialog | `[dialog] add state machine` |
| script | `[script] add sbatch parser` |
| recommender | `[recommender] add gpu estimator` |
| api | `[api] add ask endpoint` |
| frontend | `[frontend] add chat interface` |
| tests | `[tests] add knowledge loader tests` |
| docs | `[docs] update usage guide` |
| config | `[config] add redis settings` |

### 分支命名

- 功能分支：`feat/<module>-<description>`
- 修复分支：`fix/<module>-<description>`
- 文档分支：`docs/<description>`

示例：
```bash
git checkout -b feat/knowledge-faq-loader
git checkout -b fix/log-analysis-ssh-timeout
git checkout -b docs/update-api-guide
```

### 提交流程

1. 确保代码通过所有检查：
   ```bash
   pre-commit run --all-files
   pytest
   ```

2. 提交代码：
   ```bash
   git add .
   git commit -m "[knowledge] add faq loader with fuzzy matching"
   ```

3. 推送到远程：
   ```bash
   git push origin feat/knowledge-faq-loader
   ```

4. 创建 Pull Request，等待代码审查

## 测试规范

### 测试文件组织

- 每个模块有对应的测试目录：`tests/test_<module>/`
- 测试文件命名：`test_<feature>.py`
- 测试类命名：`Test<Feature>`
- 测试函数命名：`test_<scenario>`

### 测试编写示例

```python
"""知识库加载器测试."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.knowledge.loader import KnowledgeLoader


class TestKnowledgeLoader:
    """知识库加载器测试类."""

    def test_load_valid_json(self, tmp_path: Path) -> None:
        """测试加载有效的 JSON 文件."""
        # 准备测试数据
        test_file = tmp_path / "test.json"
        test_file.write_text('{"faq": []}')

        # 执行加载
        loader = KnowledgeLoader(test_file)
        result = loader.load()

        # 验证结果
        assert result is not None
        assert "faq" in result

    def test_load_empty_query(self) -> None:
        """测试空查询返回空结果."""
        loader = KnowledgeLoader()
        result = loader.search("")
        assert result == []

    def test_load_missing_file(self) -> None:
        """测试加载不存在的文件抛出异常."""
        with pytest.raises(FileNotFoundError):
            KnowledgeLoader(Path("/nonexistent/path.json"))
```

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定模块测试
pytest tests/test_knowledge/

# 运行并显示覆盖率
pytest --cov=src --cov-report=html

# 运行并输出详细信息
pytest -v -s
```

### 覆盖率要求

- 单元测试覆盖率 ≥ 80%
- 每个 API 端点必须有集成测试
- 使用 fixture 管理测试数据，不依赖外部服务

## 新增 FAQ 条目

### 1. 确定分类

参考知识库分类体系：

| 一级类 | 二级类 | 说明 |
|--------|--------|------|
| error_diagnosis | qos_limit | QOS 限制相关错误 |
| error_diagnosis | gpu_related | GPU 相关问题 |
| error_diagnosis | oom | 内存溢出问题 |
| error_diagnosis | script_error | 脚本错误 |
| error_diagnosis | env_missing | 环境缺失 |
| job_submission | interactive | 交互式作业 |
| job_submission | batch | 批处理作业 |
| job_status | queuing | 排队状态 |
| permission | quota | 配额限制 |

### 2. 编写 JSON 条目

```json
{
  "id": "faq-xxx",
  "category": "error_diagnosis",
  "title": "问题标题",
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "intents": ["意图标签1", "意图标签2"],
  "question": "用户可能问的问题？",
  "answer": "详细的回答内容，支持 Markdown 格式。\n\n**解决步骤**：\n1. 第一步\n2. 第二步",
  "related_errors": ["相关错误ID"],
  "references": ["参考文档名称"]
}
```

### 3. 添加到知识库文件

- 报错类：`src/knowledge/data/faq_errors.json`
- 使用类：`src/knowledge/data/faq_usage.json`
- 命令类：`src/knowledge/data/slurm_commands.json`
- QOS 类：`src/knowledge/data/qos_table.json`

### 4. 验证

```bash
# 运行知识库测试
pytest tests/test_knowledge/ -v

# 验证 JSON 格式
python -c "import json; json.load(open('src/knowledge/data/faq_errors.json'))"
```

## 代码审查清单

提交 Pull Request 前请自查：

- [ ] 代码通过 `ruff check` 无错误
- [ ] 代码通过 `mypy strict` 无错误
- [ ] 所有新增函数有 docstring
- [ ] 所有类型标注完整
- [ ] 单元测试覆盖新增逻辑
- [ ] 测试全部通过
- [ ] Commit message 格式正确
- [ ] 没有硬编码的敏感信息
- [ ] 文档已更新（如需要）

## 问题反馈

遇到问题请：

1. 检查是否已有相关 Issue
2. 创建新 Issue，使用对应模板
3. 提供详细的复现步骤和环境信息

---

感谢你的贡献！
