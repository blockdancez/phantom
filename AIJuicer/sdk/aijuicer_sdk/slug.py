"""产生 project_name 的便利工具。

Producer 调用 ``create_workflow`` 前可以用这里的函数从 idea 文本生成 slug。
SDK 不负责保证全局唯一——撞名时 scheduler 会自动加 4 位随机后缀。

如果 caller 想要更高质量的 slug（比如调 LLM 从中文长文本提炼"core idea name"），
完全可以不用本模块、自己生成后传给 ``create_workflow(project_name=...)``。
"""

from __future__ import annotations

import re

_MAX_LEN = 40
_MAX_WORDS = 3


def slugify_idea(text: str | None) -> str:
    """deterministic slug 生成：抽前 3 个去重的英文 / 数字词，小写 + 短横线。

    例：
        ``"AI Email Classifier"``                              → ``"ai-email-classifier"``
        ``"AI Idea · AI 驱动的助手 SaaS Web AI SaaS"``           → ``"ai-idea-saas"``
        ``"做一个面向大学生的 AI 课程笔记助手"``                     → ``"ai"``
        ``"Resume Optimizer 2.0"``                             → ``"resume-optimizer-2"``
        ``""``                                                 → ``"project"``
    """
    if not text:
        return "project"
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*|[0-9]+", text)
    cleaned: list[str] = []
    seen: set[str] = set()
    for w in words:
        lw = w.lower()
        if lw in seen:
            continue
        cleaned.append(lw)
        seen.add(lw)
        if len(cleaned) >= _MAX_WORDS:
            break
    if not cleaned:
        return "project"
    slug = "-".join(cleaned)[:_MAX_LEN].rstrip("-")
    if len(slug) < 2:
        return "project"
    return slug
