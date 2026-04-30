"""Pytest fixtures 共享。"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_workspace_base(tmp_path: Path, monkeypatch) -> Path:
    """把 PHANTOM_PROJECTS_BASE 指向 tmp_path，避免测试碰真实 ~/phantom。"""
    base = tmp_path / "phantom"
    base.mkdir()
    monkeypatch.setenv("PHANTOM_PROJECTS_BASE", str(base))
    return base
