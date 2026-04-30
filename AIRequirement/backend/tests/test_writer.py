import pytest
from unittest.mock import AsyncMock, MagicMock

from app.agent.writer import PrdWriter, _strip_outer_fence


def test_strip_outer_fence_removes_markdown_wrap():
    src = "```markdown\n# 标题\n\n正文\n```"
    assert _strip_outer_fence(src) == "# 标题\n\n正文"


def test_strip_outer_fence_keeps_inner_blocks():
    src = "# 标题\n\n```python\nprint(1)\n```\n\n结尾"
    # no outer wrap → unchanged
    assert _strip_outer_fence(src) == src


def test_strip_outer_fence_handles_no_lang_tag():
    src = "```\n纯文本\n```"
    assert _strip_outer_fence(src) == "纯文本"


def _mock_openai_response(text: str):
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.mark.asyncio
async def test_writer_generates_prd():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_openai_response("# 产品需求文档\n\n## 概述\n这是一个AI代码审查工具...")
    )

    writer = PrdWriter(openai_client=mock_client)

    result = await writer.generate(
        idea="一个AI驱动的代码审查工具",
        research={
            "keywords": ["AI", "代码审查"],
            "competitors": [
                {"title": "CodeRabbit", "url": "https://coderabbit.ai", "summary": "AI代码审查..."}
            ],
        },
    )

    assert "title" in result
    assert "content" in result
    assert len(result["content"]) > 0
    mock_client.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
async def test_writer_prompt_includes_research():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_openai_response("# PRD\n\n## 概述")
    )

    writer = PrdWriter(openai_client=mock_client)

    await writer.generate(
        idea="测试idea",
        research={
            "keywords": ["测试"],
            "competitors": [
                {"title": "竞品A", "url": "https://a.com", "summary": "竞品描述"}
            ],
        },
    )

    call_args = mock_client.chat.completions.create.call_args
    messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
    user_message = next(m["content"] for m in messages if m["role"] == "user")
    assert "竞品A" in user_message
    assert "测试idea" in user_message


@pytest.mark.asyncio
async def test_writer_edit_mode_uses_previous_prd():
    """When rerun_instruction + previous_prd are both supplied, the writer
    must enter edit mode: feed the prior PRD as the base and instruct the
    model to patch minimally rather than regenerate."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_openai_response("# PRD\n\n修改后正文")
    )

    writer = PrdWriter(openai_client=mock_client)
    await writer.generate(
        idea="原始 idea",
        research={"keywords": [], "competitors": []},
        rerun_instruction="去掉 7. MVP范围",
        previous_prd="# 上一版 PRD\n\n## 7. MVP范围\n - 功能 A\n - 功能 B",
    )

    kwargs = mock_client.chat.completions.create.call_args.kwargs
    user_msg = next(m["content"] for m in kwargs["messages"] if m["role"] == "user")
    sys_msg = next(m["content"] for m in kwargs["messages"] if m["role"] == "system")
    assert "上一版 PRD" in user_msg
    assert "去掉 7. MVP范围" in user_msg
    assert "上一版 PRD" in user_msg.split("## 上一版 PRD")[1]  # base section present
    assert "编辑模式" in sys_msg
    assert kwargs["temperature"] == 0.2  # tighter than rerun-without-base


@pytest.mark.asyncio
async def test_writer_includes_rerun_instruction():
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_mock_openai_response("# PRD\n\n## 概述")
    )

    writer = PrdWriter(openai_client=mock_client)

    await writer.generate(
        idea="测试idea",
        research={"keywords": [], "competitors": []},
        rerun_instruction="请把目标用户聚焦到 B 端 SaaS 决策者",
    )

    call_args = mock_client.chat.completions.create.call_args
    kwargs = call_args.kwargs or call_args[1]
    messages = kwargs.get("messages")
    user_message = next(m["content"] for m in messages if m["role"] == "user")
    system_message = next(m["content"] for m in messages if m["role"] == "system")
    assert "重跑指令" in user_message
    assert "B 端 SaaS 决策者" in user_message
    # rerun directive must lead the user message, not be buried mid-prompt
    assert user_message.lstrip().startswith("# ⚠️ 重跑指令")
    # system prompt should explicitly mention this is a rerun
    assert "重跑" in system_message
    # temperature tightened on rerun
    assert kwargs.get("temperature") == 0.3
