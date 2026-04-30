"""Playwright + LLM-driven product list extractor.

Used for Toolify and Traffic.cv where there's no public API. Strategy:

1. Render the listing page with Playwright (these are SPAs).
2. Pull a compact text summary plus all anchors (href + visible text).
3. Hand that to gpt-4o-mini with a Pydantic schema for structured output.
4. Resolve relative URLs against the page origin and dedupe in caller.

Anchor list rather than raw HTML keeps prompt cost predictable and gives
the model exactly the field it needs (the link target).
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import structlog
from langchain_openai import ChatOpenAI
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

from src.product_discovery.types import DiscoveredProduct

logger = structlog.get_logger()


class _ExtractedItem(BaseModel):
    name: str = Field(description="产品名（不要带后缀的 - Toolify / · X 等站名）")
    homepage_url: str = Field(description="产品的官方主页绝对 URL（不是发现源页面）")
    tagline: str | None = Field(
        default=None, description="一句话简介，可缺省"
    )


class _ExtractedList(BaseModel):
    items: list[_ExtractedItem]


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify_url(url: str) -> str:
    host = urlparse(url).hostname or url
    host = host.lstrip("www.")
    return _SLUG_RE.sub("-", host.lower()).strip("-")[:96]


async def _render_anchors(
    list_url: str, headless: bool, max_anchors: int = 200
) -> tuple[str, list[dict]]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(list_url, wait_until="networkidle", timeout=45000)
        except Exception as exc:
            logger.warning("Playwright 跳转失败", url=list_url, error=str(exc))
            try:
                await page.goto(list_url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                await browser.close()
                return "", []
        await page.wait_for_timeout(2000)
        try:
            text = (await page.inner_text("body"))[:8000]
        except Exception:
            text = ""
        anchors_raw = await page.eval_on_selector_all(
            "a[href]",
            """nodes => nodes.slice(0, 600).map(n => ({
                href: n.getAttribute('href') || '',
                text: (n.innerText || '').trim().slice(0, 120)
            }))""",
        )
        await browser.close()

    seen = set()
    anchors: list[dict] = []
    for a in anchors_raw:
        href = a.get("href") or ""
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = urljoin(list_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        anchors.append({"url": absolute, "text": a.get("text") or ""})
        if len(anchors) >= max_anchors:
            break
    return text, anchors


_PROMPT = """你正在帮我从一个产品发现网站的列表页面里提取出"被推荐的产品"。

发现源站点：{source_name}（{list_url}）

下面是页面的可见文本片段（截断）：
---
{text}
---

下面是页面上的所有链接（href + 锚文本），请从中识别出**指向产品本身的官方主页**的那些链接（不要选发现源自己内部的导航/分类/详情页 URL）：

{anchors}

请返回前 {top_n} 个你认为最像"被该发现源推荐的真实产品主页"的项。
- name 用产品自己的名字（去掉发现源后缀）
- homepage_url 用绝对 URL，必须不是 {source_host} 自己的域名
- tagline 如果文本里看得出就给一句话简介，否则留空
"""


async def discover_via_llm(
    source_name: str,
    list_url: str,
    discovered_from: str,
    headless: bool,
    top_n: int = 20,
) -> list[DiscoveredProduct]:
    text, anchors = await _render_anchors(list_url, headless=headless)
    if not anchors:
        logger.warning("产品发现_无锚点", source=discovered_from)
        return []

    source_host = urlparse(list_url).hostname or ""
    anchors_block = "\n".join(
        f"- [{a['text']!r}] {a['url']}" for a in anchors[:200]
    )
    prompt = _PROMPT.format(
        source_name=source_name,
        list_url=list_url,
        text=text or "(无文本)",
        anchors=anchors_block,
        top_n=top_n,
        source_host=source_host,
    )

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(
        _ExtractedList
    )
    try:
        result: _ExtractedList = await llm.ainvoke(prompt)
    except Exception as exc:
        logger.warning("产品发现_LLM 失败", source=discovered_from, error=str(exc))
        return []

    out: list[DiscoveredProduct] = []
    seen_urls: set[str] = set()
    for item in result.items[:top_n]:
        url = item.homepage_url.strip()
        host = urlparse(url).hostname or ""
        if not url.startswith(("http://", "https://")):
            continue
        if source_host and source_host in host:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        out.append(
            DiscoveredProduct(
                slug=f"{discovered_from}-{_slugify_url(url)}",
                name=item.name.strip()[:240],
                homepage_url=url,
                tagline=(item.tagline or "").strip()[:500] or None,
                discovered_from=discovered_from,
            )
        )
    logger.info("产品发现抽取", source=discovered_from, count=len(out))
    return out
