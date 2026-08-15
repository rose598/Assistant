"""脚本模块：sbatch 解析 / 模板 / 生成（第 5 周）。

对外暴露：
- ``SbatchParser``：sbatch 指令解析器（parser.py，A 职责）；
- ``ScriptTemplate`` / ``TEMPLATES``：模板定义，A/B 共享（templates.py）；
- ``ScriptGenerator``：模板脚本生成器（generator.py）；
- ``ScriptDiffer`` / ``DiffSummary``：差分显示（differ.py，A 自测）；
- ``RewriteState`` / ``RewriteContext`` / ``ScriptRewriteFlow``：对话式
  脚本改写流程（rewrite_flow.py，对应原计划 dialog/flow.py，
  按脚本域归属落位）。

后续改写流程 / 差分显示 / 导出等子模块陆续追加并在此补充导出。
"""

from src.script.differ import DiffSummary, ScriptDiffer
from src.script.generator import ScriptGenerator
from src.script.parser import SbatchParser
from src.script.rewrite_flow import RewriteContext, RewriteState, ScriptRewriteFlow
from src.script.templates import TEMPLATES, ScriptTemplate

__all__ = [
    "DiffSummary",
    "RewriteContext",
    "RewriteState",
    "SbatchParser",
    "ScriptDiffer",
    "ScriptGenerator",
    "ScriptRewriteFlow",
    "ScriptTemplate",
    "TEMPLATES",
]
