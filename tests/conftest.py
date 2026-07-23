"""pytest 全局配置与 fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    """返回项目根目录路径."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def knowledge_dir(project_root: Path) -> Path:
    """返回知识库数据目录."""
    return project_root / "src" / "knowledge" / "data"
