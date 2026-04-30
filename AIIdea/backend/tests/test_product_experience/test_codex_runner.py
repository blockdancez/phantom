"""单测 codex_runner: subprocess wrapper + 报告读取 + 错误分类。

不真跑 codex —— mock asyncio.create_subprocess_exec 与文件系统。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.product_experience.codex_runner import (
    ExperienceRunResult,
    build_codex_prompt,
    run_codex_experience,
)


def test_build_prompt_contains_all_constraints():
    prompt = build_codex_prompt(
        product_name="Toolify",
        product_url="https://toolify.ai",
        requires_login=True,
        work_dir=Path("/tmp/exp/abc"),
    )
    # 输入参数必须出现
    assert "Toolify" in prompt
    assert "https://toolify.ai" in prompt
    assert "true" in prompt.lower()  # requires_login=true
    # 输出位置约定
    assert "/tmp/exp/abc/REPORT.md" in prompt
    assert "/tmp/exp/abc/screenshots" in prompt
    # 借鉴启发 brief 5 个核心段（前置）
    for h in ("## 产品理念", "## 目标用户画像", "## 核心功能（含设计意图）",
              "## 差异化机会", "## 创新切入点"):
        assert h in prompt
    # 旧 8 段保留作"附录"做向后兼容
    for h in ("## 概览", "## 登录情况", "## 功能盘点",
              "## 优点", "## 缺点", "## 商业模式",
              "## 目标用户", "## 综合体验分"):
        assert h in prompt
    # 必须显式提示用 chrome-devtools MCP（而非自己 fetch HTML）
    assert "chrome-devtools" in prompt
    # yaml 块约定
    assert "```yaml" in prompt


@pytest.mark.asyncio
async def test_run_codex_experience_happy_path(tmp_path: Path):
    """codex 退出码 0 + REPORT.md 存在 → status=completed, markdown 回填。"""
    base_dir = tmp_path / "experience"

    sample_md = (
        "# 产品体验报告\n\n## 概览\nFakeProduct 是一个测试产品。\n\n"
        "## 登录情况\ngoogle\n\n## 功能盘点\n- F: P | N\n\n"
        "## 优点\n好。\n\n## 缺点\n差。\n\n"
        "## 商业模式\n订阅。\n\n## 目标用户\n开发者。\n\n"
        "## 综合体验分\n75\n"
    )

    captured: dict[str, Any] = {}

    async def fake_subprocess_exec(*args, **kwargs):
        # 真实 codex 命令应以 "codex" + "exec" 开头
        captured["argv"] = list(args)
        captured["cwd"] = kwargs.get("cwd")
        # 模拟 codex 把报告写出去
        work_dir = Path(kwargs["cwd"])
        (work_dir / "REPORT.md").write_text(sample_md, encoding="utf-8")
        (work_dir / "screenshots").mkdir(exist_ok=True)
        (work_dir / "screenshots" / "landing.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ok\n", b""))
        proc.wait = AsyncMock(return_value=0)
        return proc

    with patch(
        "src.product_experience.codex_runner.asyncio.create_subprocess_exec",
        new=fake_subprocess_exec,
    ):
        result = await run_codex_experience(
            slug="fake",
            name="FakeProduct",
            url="https://fake.test",
            requires_login=True,
            report_id="abc123",
            base_dir=base_dir,
            codex_binary="codex",
            timeout_seconds=10,
        )

    # 命令构造正确
    assert captured["argv"][0] == "codex"
    assert captured["argv"][1] == "exec"
    assert "--dangerously-bypass-approvals-and-sandbox" in captured["argv"]
    assert "--skip-git-repo-check" in captured["argv"]
    # 工作目录是 base_dir/<report_id>
    assert captured["cwd"].endswith("abc123")

    # 返回值
    assert isinstance(result, ExperienceRunResult)
    assert "FakeProduct 是一个测试产品" in result.markdown
    assert result.login_status == "google"
    assert len(result.screenshots) == 1
    assert result.screenshots[0]["name"] == "landing"
    assert result.screenshots[0]["path"].endswith("landing.png")
    assert "stdout" in result.trace


@pytest.mark.asyncio
async def test_run_codex_experience_timeout_kills_process(tmp_path: Path):
    """timeout → terminate() + 返回 status_failed-friendly 结果。"""
    base_dir = tmp_path / "experience"

    proc = MagicMock()
    proc.returncode = None  # 仍在跑
    proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
    proc.terminate = MagicMock()
    proc.wait = AsyncMock(return_value=-15)

    async def fake_subprocess_exec(*args, **kwargs):
        return proc

    with patch(
        "src.product_experience.codex_runner.asyncio.create_subprocess_exec",
        new=fake_subprocess_exec,
    ):
        result = await run_codex_experience(
            slug="fake",
            name="FakeProduct",
            url="https://fake.test",
            requires_login=False,
            report_id="t1",
            base_dir=base_dir,
            timeout_seconds=1,
        )

    proc.terminate.assert_called_once()
    assert result.markdown == ""
    assert result.login_status == "failed"
    assert result.trace["reason"] == "timeout"


@pytest.mark.asyncio
async def test_run_codex_experience_no_report_when_codex_exits_clean(tmp_path: Path):
    """codex 退出 0 但忘了写 REPORT.md → 视为失败，trace 标 reason。"""
    base_dir = tmp_path / "experience"

    async def fake_subprocess_exec(*args, **kwargs):
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    with patch(
        "src.product_experience.codex_runner.asyncio.create_subprocess_exec",
        new=fake_subprocess_exec,
    ):
        result = await run_codex_experience(
            slug="fake",
            name="FakeProduct",
            url="https://fake.test",
            requires_login=False,
            report_id="t2",
            base_dir=base_dir,
            timeout_seconds=10,
        )

    assert result.markdown == ""
    assert result.login_status == "failed"
    assert result.trace["reason"] == "no_report_or_nonzero_exit"
