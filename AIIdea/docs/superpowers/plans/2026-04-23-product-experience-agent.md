# 产品体验 Agent 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增"产品体验分析"管线 —— 用 Playwright 持久化浏览器配置驱动 LangGraph agent 真实访问目标产品网站、必要时用 Google 登录进入产品内部、深度浏览各功能页、对每个产品产出一份结构化体验报告并落库展示。

**Architecture:** 复用项目现有 stack（Playwright + LangGraph + ChatOpenAI + APScheduler + 新表 + 新 API + 新前端路由）。三个 MVP 目标站点（producthunt.com / toolify.ai / traffic.cv）通过 `product_targets` 注册表配置；浏览器使用 `chromium.launch_persistent_context(user_data_dir=backend/data/browser_profile, channel="chrome")`，由用户**一次性**通过 bootstrap 脚本手动登录 Google，之后所有 cron 运行复用该会话。新增独立 `experience_products` cron（默认 6 小时一次），每次轮询出最久未跑过的目标，跑完写一行 `product_experience_reports`，前端 `/products` 路由列表 + 详情页（含截图画廊）展示。

**Tech Stack:** Python 3.12 / FastAPI / Playwright (chrome channel, persistent context) / LangGraph ReAct / langchain-openai gpt-4o / SQLAlchemy 2.0 async + JSONB / Alembic / APScheduler / Next.js 16 (webpack) / React 19 / Tailwind v4.

---

## Context

### 用户决策（2026-04-23）

1. **目标站点**：`producthunt.com` / `www.toolify.ai` / `traffic.cv`（MVP 3 个；架构以注册表驱动便于追加）
2. **体验深度**：进入产品内部。"如果支持 Google 登录就用 Google 登录，否则只看营销页"
3. **浏览器**：复用 Playwright（项目里 Twitter collector 已用）
4. **触发**：周期 cron
5. **存储**：新表

### Google 登录的取舍

Google 反自动化很激进，**Playwright 不能可靠地脚本式跑通"输入密码 + 二次验证"**（账号会被风控、需要手机/邮箱二次验证、有时强制 FedCM）。本方案选**持久化用户数据目录 + 真 Chrome channel** 路线：

- 用户**一次性**手动跑 `backend/scripts/bootstrap_browser_profile.py`，脚本以**有头**模式拉起一个真 Chrome（`channel="chrome"`），使用固定 `user_data_dir=backend/data/browser_profile`。用户在弹出的浏览器里走完 Google 登录，关掉窗口。Cookie + localStorage + IndexedDB 全部写入该 profile 目录。
- 之后 cron 运行**复用同一个 user_data_dir**，目标站点点击"Sign in with Google"时，Google OAuth 弹窗看到已登录会话直接 auto-consent 返回 → 等价于已登录目标站。
- profile 目录写进 `.gitignore`，不入库；不写明文密码到任何地方。
- Google 会话 cookie 有效期通常以**周/月**为单位；过期后 cron 跑会捕获到登录失败、写 `login_used="failed"` 到本次报告，并发 INFO 日志提示用户重跑 bootstrap 脚本。

### 已知风险（写进代码注释 + 文档）

- 目标站点改 DOM 会让 "Sign in with Google" 按钮选择器失效 → 内置 6 个常见模式列表 + LLM agent fallback 兜底（让 LLM 看截图找按钮）
- 截图无清理策略（disk 会涨）→ MVP 接受，后续 plan 加 retention
- ReAct 可能死循环 → LangGraph `recursion_limit=30` + scheduler 层 8 分钟 wall-clock timeout
- 单 worker in-process 锁（与项目其他 job 一致），多 worker 部署时会失效

---

## File Structure

### 新建后端文件

```
backend/src/product_experience/
├── __init__.py
├── registry.py                  # PRODUCT_TARGETS 注册表（3 条 MVP）
├── browser.py                   # Playwright 持久化上下文封装
├── google_login.py              # 检测并点击 "Sign in with Google" 按钮
├── tools.py                     # LangGraph 工具：navigate/click/extract/screenshot/try_login
├── prompts.py                   # 中文 SYSTEM_PROMPT
├── graph.py                     # LangGraph ReAct 装配
└── extractor.py                 # 解析 agent 终态 markdown → ProductExperienceReport schema

backend/src/models/product_experience_report.py   # SQLAlchemy ORM
backend/src/schemas/product_experience_report.py  # Pydantic
backend/src/api/product_experience_reports.py     # 列表 + 详情

backend/alembic/versions/c4d8f1e62a93_add_product_experience_reports.py

backend/scripts/bootstrap_browser_profile.py      # 一次性 Google 登录引导

backend/data/browser_profile/                     # gitignored，运行时创建
backend/data/product_screenshots/                 # gitignored，运行时创建
```

### 新建测试文件

```
backend/tests/test_product_experience/__init__.py
backend/tests/test_product_experience/test_registry.py
backend/tests/test_product_experience/test_browser.py
backend/tests/test_product_experience/test_google_login.py
backend/tests/test_product_experience/test_tools.py
backend/tests/test_product_experience/test_extractor.py
backend/tests/test_api/test_product_experience_reports.py
backend/tests/test_scheduler_experience.py
```

### 新建前端文件

```
frontend/src/app/products/page.tsx
frontend/src/app/products/[id]/page.tsx
frontend/src/app/products/not-found.tsx
frontend/src/components/product-experience-card.tsx
frontend/src/components/product-experience-filter-bar.tsx
frontend/src/components/screenshot-gallery.tsx
```

### 修改文件

```
backend/.gitignore                       # 新增 data/ 排除
backend/src/api/router.py                # 注册 product_experience_reports 路由
backend/src/api/pipeline.py              # 加 experience_products 到 job 矩阵
backend/src/scheduler/jobs.py            # 加 experience_products cron
backend/src/main.py                      # 挂载 /static/screenshots 静态目录
backend/src/config.py                    # 加 experience_interval_minutes
backend/pyproject.toml                   # 无新增 dep（playwright 已在）

frontend/src/lib/types.ts                # 加 ProductExperienceReport 类型
frontend/src/lib/api.ts                  # 加 list/detail fetch
frontend/src/components/sidebar.tsx      # 加 /products 导航项
```

---

## Tasks

### Task 1: 注册表

**Files:**
- Create: `backend/src/product_experience/__init__.py`
- Create: `backend/src/product_experience/registry.py`
- Create: `backend/tests/test_product_experience/__init__.py`
- Create: `backend/tests/test_product_experience/test_registry.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_product_experience/test_registry.py
from src.product_experience.registry import PRODUCT_TARGETS, get_target


def test_registry_has_three_mvp_targets():
    urls = {t.url for t in PRODUCT_TARGETS}
    assert "https://www.producthunt.com" in urls
    assert "https://www.toolify.ai" in urls
    assert "https://traffic.cv" in urls


def test_registry_targets_are_unique_by_slug():
    slugs = [t.slug for t in PRODUCT_TARGETS]
    assert len(slugs) == len(set(slugs))


def test_get_target_by_slug():
    t = get_target("toolify")
    assert t is not None
    assert t.url == "https://www.toolify.ai"


def test_get_target_returns_none_for_unknown():
    assert get_target("not-a-real-slug") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_product_experience/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.product_experience'`

- [ ] **Step 3: 实现注册表**

```python
# backend/src/product_experience/__init__.py
```

(空文件，仅作为 package marker)

```python
# backend/src/product_experience/registry.py
from dataclasses import dataclass


@dataclass(frozen=True)
class ProductTarget:
    """一个待体验的产品。

    slug: 唯一短标识，用于 cron 调度选最久未跑的、用于截图目录命名
    url: 入口 URL（首页）
    name: 给 LLM / UI 看的可读名
    requires_login: True 表示需要登录才能体验主要功能；False 只看营销页
    """

    slug: str
    url: str
    name: str
    requires_login: bool


PRODUCT_TARGETS: list[ProductTarget] = [
    ProductTarget(
        slug="producthunt",
        url="https://www.producthunt.com",
        name="Product Hunt",
        requires_login=True,
    ),
    ProductTarget(
        slug="toolify",
        url="https://www.toolify.ai",
        name="Toolify",
        requires_login=True,
    ),
    ProductTarget(
        slug="traffic-cv",
        url="https://traffic.cv",
        name="Traffic.cv",
        requires_login=True,
    ),
]


def get_target(slug: str) -> ProductTarget | None:
    for t in PRODUCT_TARGETS:
        if t.slug == slug:
            return t
    return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_product_experience/test_registry.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/product_experience/ backend/tests/test_product_experience/__init__.py backend/tests/test_product_experience/test_registry.py
git commit -m "feat(product-experience): add product target registry"
```

---

### Task 2: SQLAlchemy 模型

**Files:**
- Create: `backend/src/models/product_experience_report.py`
- Modify: `backend/src/models/__init__.py`（如果存在则追加导出，否则跳过此文件改动）

- [ ] **Step 1: 写实现**

```python
# backend/src/models/product_experience_report.py
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.models.source_item import Base  # 复用现有 declarative Base


class ProductExperienceReport(Base):
    """一次产品体验的结构化报告（一个 product × 一次 run = 一行）。"""

    __tablename__ = "product_experience_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # 体验对象
    product_slug = Column(String(64), nullable=False, index=True)
    product_url = Column(Text, nullable=False)
    product_name = Column(String(256), nullable=False)

    # 运行元数据
    run_started_at = Column(DateTime(timezone=True), nullable=False)
    run_completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(16), nullable=False)  # completed | partial | failed
    failure_reason = Column(Text, nullable=True)

    # 登录情况
    login_used = Column(String(16), nullable=False)  # google | none | failed | skipped

    # 报告主体
    overall_ux_score = Column(Float, nullable=True)  # 0-100
    summary_zh = Column(Text, nullable=True)
    feature_inventory = Column(JSONB, nullable=True)  # list[{name, where_found, notes}]
    strengths = Column(Text, nullable=True)
    weaknesses = Column(Text, nullable=True)
    monetization_model = Column(Text, nullable=True)
    target_user = Column(Text, nullable=True)

    # 媒体 + trace
    screenshots = Column(JSONB, nullable=True)  # list[{name, path, taken_at}]
    agent_trace = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
```

- [ ] **Step 2: 验证 import 不报错**

Run: `cd backend && python -c "from src.models.product_experience_report import ProductExperienceReport; print(ProductExperienceReport.__tablename__)"`
Expected: 输出 `product_experience_reports`

- [ ] **Step 3: 提交**

```bash
git add backend/src/models/product_experience_report.py
git commit -m "feat(product-experience): add ProductExperienceReport ORM model"
```

---

### Task 3: Alembic 迁移

**Files:**
- Create: `backend/alembic/versions/c4d8f1e62a93_add_product_experience_reports.py`

- [ ] **Step 1: 自动生成迁移**

```bash
cd backend && PYTHONPATH=. alembic -c alembic.ini revision --autogenerate -m "add_product_experience_reports"
```

Expected: 在 `backend/alembic/versions/` 下生成一个新 `*_add_product_experience_reports.py` 文件。

- [ ] **Step 2: 检查生成内容包含建表语句**

打开生成的迁移文件，确认 `op.create_table('product_experience_reports', ...)` 存在且包含上一步 ORM 里的所有列。如果缺列（autogenerate 偶尔漏 JSONB / UUID 的 server_default），手动补齐。

特别检查 `product_slug` 列上有 `op.create_index('ix_product_experience_reports_product_slug', ...)` 调用。

- [ ] **Step 3: 跑迁移**

```bash
cd backend && PYTHONPATH=. alembic -c alembic.ini upgrade head
```

Expected: 输出 `Running upgrade <prev> -> c4d8f1e62a93, add_product_experience_reports` 无错误。

- [ ] **Step 4: psql 验证表存在**

```bash
psql "$DATABASE_URL" -c "\d product_experience_reports" 2>/dev/null | head -40
```

Expected: 列出 16+ 列含 `id` / `product_slug` / `screenshots`(jsonb) / `agent_trace`(jsonb)。

- [ ] **Step 5: 提交**

```bash
git add backend/alembic/versions/*_add_product_experience_reports.py
git commit -m "feat(product-experience): alembic migration for product_experience_reports"
```

---

### Task 4: Pydantic Schemas

**Files:**
- Create: `backend/src/schemas/product_experience_report.py`

- [ ] **Step 1: 写实现**

```python
# backend/src/schemas/product_experience_report.py
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FeatureInventoryItem(BaseModel):
    """LLM 输出的一项功能盘点条目。"""

    name: str
    where_found: str = ""
    notes: str = ""


class ScreenshotEntry(BaseModel):
    name: str
    path: str  # 相对 backend/data/product_screenshots/ 的路径，前端拼 /static/screenshots/<path>
    taken_at: datetime


class ProductExperienceReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_slug: str
    product_url: str
    product_name: str
    run_started_at: datetime
    run_completed_at: datetime | None
    status: str
    failure_reason: str | None
    login_used: str
    overall_ux_score: float | None
    summary_zh: str | None
    feature_inventory: list[FeatureInventoryItem] | None
    strengths: str | None
    weaknesses: str | None
    monetization_model: str | None
    target_user: str | None
    screenshots: list[ScreenshotEntry] | None
    agent_trace: dict[str, Any] | None
    created_at: datetime


class ProductExperienceReportListOut(BaseModel):
    """列表用裁剪版本，不带 trace / 截图详情，只带摘要字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_slug: str
    product_name: str
    product_url: str
    run_completed_at: datetime | None
    status: str
    login_used: str
    overall_ux_score: float | None
    summary_zh: str | None
    screenshots_count: int = Field(default=0)


class ProductExperienceListResponse(BaseModel):
    items: list[ProductExperienceReportListOut]
    total: int
    page: int
    per_page: int
```

- [ ] **Step 2: 验证 import**

Run: `cd backend && python -c "from src.schemas.product_experience_report import ProductExperienceReportOut; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 提交**

```bash
git add backend/src/schemas/product_experience_report.py
git commit -m "feat(product-experience): pydantic schemas"
```

---

### Task 5: gitignore 更新

**Files:**
- Modify: `backend/.gitignore`

- [ ] **Step 1: 追加排除**

在 `backend/.gitignore` 末尾追加：

```
# Product experience runtime data — regenerated locally / on server
data/browser_profile/
data/product_screenshots/
```

- [ ] **Step 2: 验证不会误杀别的内容**

```bash
cd backend && git status --ignored data/ 2>/dev/null; echo "---"; mkdir -p data/browser_profile data/product_screenshots && git status data/
```

Expected: `data/` 不出现在 `git status`。

- [ ] **Step 3: 提交**

```bash
git add backend/.gitignore
git commit -m "chore: gitignore product experience runtime dirs"
```

---

### Task 6: Playwright 持久化浏览器封装

**Files:**
- Create: `backend/src/product_experience/browser.py`
- Create: `backend/tests/test_product_experience/test_browser.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_product_experience/test_browser.py
from pathlib import Path

from src.product_experience.browser import (
    DEFAULT_USER_DATA_DIR,
    BrowserSession,
)


def test_default_user_data_dir_under_backend_data():
    assert DEFAULT_USER_DATA_DIR.name == "browser_profile"
    assert DEFAULT_USER_DATA_DIR.parent.name == "data"


async def test_browser_session_creates_user_data_dir(tmp_path: Path):
    target_dir = tmp_path / "profile"
    session = BrowserSession(user_data_dir=target_dir, headless=True)
    async with session.open() as ctx:
        page = await ctx.new_page()
        await page.goto("about:blank")
        assert await page.title() == ""
    assert target_dir.exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_product_experience/test_browser.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: 实现 BrowserSession**

```python
# backend/src/product_experience/browser.py
"""Playwright persistent browser context wrapper.

设计要点：
- 用 `launch_persistent_context(user_data_dir, channel="chrome")`，让浏览器
  cookie/localStorage 跨进程持久化 → bootstrap 脚本登一次 Google，
  之后所有 cron 跑都自带登录态。
- channel="chrome" 用本机真 Chrome（需 `playwright install chrome` 装过），
  比默认 Chromium 反自动化指纹少一些。
- 关 `--enable-automation` 这类指纹（args + JS patch navigator.webdriver）。
"""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import structlog
from playwright.async_api import BrowserContext, async_playwright

logger = structlog.get_logger()

# backend/src/product_experience/browser.py → 上溯到 backend/data/browser_profile
DEFAULT_USER_DATA_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "browser_profile"
)

_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""


class BrowserSession:
    def __init__(
        self,
        user_data_dir: Path = DEFAULT_USER_DATA_DIR,
        headless: bool = True,
        channel: str = "chrome",
    ) -> None:
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.channel = channel

    @asynccontextmanager
    async def open(self) -> AsyncIterator[BrowserContext]:
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as p:
            launch_kwargs = {
                "user_data_dir": str(self.user_data_dir),
                "headless": self.headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-default-browser-check",
                    "--no-first-run",
                ],
            }
            try:
                ctx = await p.chromium.launch_persistent_context(
                    channel=self.channel, **launch_kwargs
                )
            except Exception as e:
                logger.warning(
                    "browser_chrome_channel_unavailable_fallback_chromium",
                    error=str(e),
                )
                ctx = await p.chromium.launch_persistent_context(**launch_kwargs)

            await ctx.add_init_script(_STEALTH_INIT_SCRIPT)
            try:
                yield ctx
            finally:
                await ctx.close()
```

- [ ] **Step 4: 装 Chrome channel（一次性环境准备）**

Run:
```bash
cd backend && python -m playwright install chrome
```

Expected: `Chrome <ver> downloaded` 或 `<ver> already installed`。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && pytest tests/test_product_experience/test_browser.py -v`
Expected: 2 passed（注意第 2 个测试会真起一个浏览器，几秒）。

- [ ] **Step 6: 提交**

```bash
git add backend/src/product_experience/browser.py backend/tests/test_product_experience/test_browser.py
git commit -m "feat(product-experience): playwright persistent browser wrapper"
```

---

### Task 7: Google 登录辅助

**Files:**
- Create: `backend/src/product_experience/google_login.py`
- Create: `backend/tests/test_product_experience/test_google_login.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_product_experience/test_google_login.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.product_experience.google_login import (
    GOOGLE_BUTTON_SELECTORS,
    try_google_login,
)


def test_selectors_are_non_empty():
    assert len(GOOGLE_BUTTON_SELECTORS) >= 4
    assert all("oogle" in s.lower() or "google" in s.lower() for s in GOOGLE_BUTTON_SELECTORS)


@pytest.mark.asyncio
async def test_try_google_login_returns_false_when_no_button():
    page = MagicMock()
    page.locator = MagicMock(return_value=MagicMock(
        first=MagicMock(),
        count=AsyncMock(return_value=0),
    ))
    result = await try_google_login(page)
    assert result is False


@pytest.mark.asyncio
async def test_try_google_login_clicks_first_visible_button():
    btn = MagicMock()
    btn.click = AsyncMock()
    btn.wait_for = AsyncMock()
    locator = MagicMock(first=btn, count=AsyncMock(return_value=1))
    page = MagicMock()
    page.locator = MagicMock(return_value=locator)
    page.wait_for_load_state = AsyncMock()
    # 模拟登录后 URL 回到目标域名（含 'callback' 子串）
    page.url = "https://example.com/callback?code=xxx"
    page.context = MagicMock()
    page.context.pages = [page]

    result = await try_google_login(page)
    assert result is True
    btn.click.assert_awaited()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_product_experience/test_google_login.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: 实现 try_google_login**

```python
# backend/src/product_experience/google_login.py
"""检测页面里 'Sign in with Google' 类按钮并点击。

依赖 BrowserSession 已经预先用同一个 user_data_dir 登录过 Google：
点击后 OAuth popup 看到 Google 已登录会话 → auto-consent 返回原站 → 等价已登录。
"""
import asyncio

import structlog
from playwright.async_api import Page

logger = structlog.get_logger()

# 覆盖 6 种最常见模式；按"最具体到最宽泛"排序
GOOGLE_BUTTON_SELECTORS: list[str] = [
    'button:has-text("Continue with Google")',
    'button:has-text("Sign in with Google")',
    'a:has-text("Continue with Google")',
    'a:has-text("Sign in with Google")',
    '[aria-label*="Sign in with Google" i]',
    '[data-provider="google"]',
]


async def try_google_login(page: Page, timeout_ms: int = 15000) -> bool:
    """尝试在当前页面找到并点击 Google 登录按钮。

    返回 True 表示按钮被点击且页面在 timeout 内有 navigation 发生；
    False 表示没找到按钮或登录后没回到非登录页。
    """
    for selector in GOOGLE_BUTTON_SELECTORS:
        try:
            locator = page.locator(selector)
            count = await locator.count()
            if count == 0:
                continue
            btn = locator.first
            await btn.wait_for(state="visible", timeout=2000)
            logger.info("google_login_button_found", selector=selector)

            # popup 模式 + 同窗口跳转模式都要兼容
            try:
                async with page.context.expect_page(timeout=3000) as popup_info:
                    await btn.click()
                popup = await popup_info.value
                await popup.wait_for_load_state("networkidle", timeout=timeout_ms)
                # 等 popup 自动关闭（已登录会话 → consent → close）
                for _ in range(20):
                    if popup.is_closed():
                        break
                    await asyncio.sleep(0.5)
            except Exception:
                # 没弹 popup → 走同窗口跳转
                await btn.click()
                await page.wait_for_load_state("networkidle", timeout=timeout_ms)

            # 简单成功判定：URL 不再停在 accounts.google.com
            if "accounts.google.com" not in page.url:
                logger.info("google_login_success", final_url=page.url[:100])
                return True
            logger.info("google_login_blocked_at_google", final_url=page.url[:100])
            return False
        except Exception as e:
            logger.info("google_login_selector_failed", selector=selector, error=str(e)[:120])
            continue

    logger.info("google_login_no_button_found")
    return False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_product_experience/test_google_login.py -v`
Expected: 3 passed.

- [ ] **Step 5: 提交**

```bash
git add backend/src/product_experience/google_login.py backend/tests/test_product_experience/test_google_login.py
git commit -m "feat(product-experience): google login button detection"
```

---

### Task 8: Bootstrap 脚本

**Files:**
- Create: `backend/scripts/bootstrap_browser_profile.py`

- [ ] **Step 1: 实现脚本**

```python
# backend/scripts/bootstrap_browser_profile.py
"""一次性引导：以有头 Chrome 拉起 Playwright，让用户手动登录 Google。

跑法：
    cd backend && PYTHONPATH=. python scripts/bootstrap_browser_profile.py

脚本会打开真 Chrome 窗口，导航到 https://accounts.google.com。
用户手动登录完后，回到终端按 Enter 即可关闭浏览器，
profile 数据已经写到 backend/data/browser_profile。
"""
import asyncio
import sys

from src.product_experience.browser import DEFAULT_USER_DATA_DIR, BrowserSession


async def main() -> None:
    print(f"[bootstrap] user_data_dir = {DEFAULT_USER_DATA_DIR}")
    print("[bootstrap] 即将打开 Chrome 窗口，请在窗口里完成 Google 登录。")
    print("[bootstrap] 登录完成后请回到本终端按 Enter 退出。")

    session = BrowserSession(headless=False)
    async with session.open() as ctx:
        page = await ctx.new_page()
        await page.goto("https://accounts.google.com")
        # 阻塞等用户按 Enter
        await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
    print("[bootstrap] 已关闭浏览器，profile 已保存。")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 验证 lint / import**

Run: `cd backend && python -c "import ast; ast.parse(open('scripts/bootstrap_browser_profile.py').read()); print('syntax ok')"`
Expected: `syntax ok`

- [ ] **Step 3: 提交**

```bash
git add backend/scripts/bootstrap_browser_profile.py
git commit -m "feat(product-experience): bootstrap script for one-time Google login"
```

---

### Task 9: Agent 工具

**Files:**
- Create: `backend/src/product_experience/tools.py`
- Create: `backend/tests/test_product_experience/test_tools.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_product_experience/test_tools.py
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.product_experience.tools import (
    BrowserToolDeps,
    extract_visible_text,
    take_screenshot,
)


@pytest.mark.asyncio
async def test_extract_visible_text_returns_inner_text():
    page = MagicMock()
    page.inner_text = AsyncMock(return_value="Hello World\n\nThis is content.")
    text = await extract_visible_text(page)
    assert "Hello World" in text
    assert "content" in text


@pytest.mark.asyncio
async def test_take_screenshot_writes_file_and_returns_relative_path(tmp_path: Path):
    page = MagicMock()
    captured: dict[str, bytes] = {}

    async def fake_screenshot(path: str, full_page: bool = False) -> None:
        captured["path"] = path
        Path(path).write_bytes(b"png-bytes")

    page.screenshot = fake_screenshot
    deps = BrowserToolDeps(report_id="r1", screenshot_root=tmp_path)
    rel = await take_screenshot(page, deps, name="landing")
    assert rel.startswith("r1/")
    assert rel.endswith(".png")
    assert (tmp_path / rel).exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_product_experience/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: 实现工具**

```python
# backend/src/product_experience/tools.py
"""LangGraph agent 用的浏览器工具集。

工具函数采用「显式依赖注入」而非闭包：BrowserToolDeps 携带本次 run 共用的
report_id / screenshot_root / page handle。Graph 层负责把这些 dep 装到
LangChain Tool wrapper 里再交给 LLM。
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import structlog
from playwright.async_api import Page

logger = structlog.get_logger()


@dataclass
class BrowserToolDeps:
    report_id: str
    screenshot_root: Path
    page: Page | None = None  # graph 装配后填


async def navigate(page: Page, url: str, timeout_ms: int = 30000) -> str:
    """跳转到指定 URL，等到 networkidle，返回最终 URL + 标题。"""
    await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
    title = await page.title()
    logger.info("agent_navigate", url=url, final_url=page.url[:200], title=title[:120])
    return f"navigated to {page.url}\ntitle: {title}"


async def click(page: Page, selector: str, timeout_ms: int = 5000) -> str:
    """点击 selector 命中的第一个元素，等待页面稳定。"""
    await page.locator(selector).first.click(timeout=timeout_ms)
    await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    logger.info("agent_click", selector=selector, after_url=page.url[:200])
    return f"clicked {selector}; now at {page.url}"


async def extract_visible_text(page: Page) -> str:
    """返回 body 可见文本，截断到 4000 字符防止 LLM context 爆。"""
    text = await page.inner_text("body")
    if len(text) > 4000:
        text = text[:4000] + "\n... [truncated]"
    return text


async def take_screenshot(page: Page, deps: BrowserToolDeps, name: str) -> str:
    """截当前 viewport，存成 backend/data/product_screenshots/<report_id>/<name>-<uuid>.png。

    返回相对 screenshot_root 的路径（前端拼 /static/screenshots/<rel> 即可访问）。
    """
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:48]
    rel_dir = deps.report_id
    abs_dir = deps.screenshot_root / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{safe_name}-{uuid4().hex[:8]}.png"
    abs_path = abs_dir / fname
    await page.screenshot(path=str(abs_path), full_page=False)
    rel = f"{rel_dir}/{fname}"
    logger.info(
        "agent_screenshot",
        rel_path=rel,
        bytes=abs_path.stat().st_size if abs_path.exists() else 0,
        taken_at=datetime.now(tz=timezone.utc).isoformat(),
    )
    return rel
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_product_experience/test_tools.py -v`
Expected: 2 passed.

- [ ] **Step 5: 提交**

```bash
git add backend/src/product_experience/tools.py backend/tests/test_product_experience/test_tools.py
git commit -m "feat(product-experience): browser agent tools"
```

---

### Task 10: SYSTEM_PROMPT

**Files:**
- Create: `backend/src/product_experience/prompts.py`

- [ ] **Step 1: 写实现**

```python
# backend/src/product_experience/prompts.py
"""产品体验 agent 的中文 system prompt。

工作流强约束（防 ReAct 漫游）：
1. navigate 到入口
2. 截一张 landing 截图，extract_visible_text 看产品做啥
3. 如果 requires_login=True：try_google_login
   - 成功 → 进入产品内部继续探索
   - 失败 → 只看营销页（about / pricing / docs / changelog 等），并在最终
     报告 login_used 字段标 'failed'
4. 列举主导航的链接，逐一 navigate + 截图 + extract_text，最多探 6 个页面
5. 输出严格 markdown 报告，字段顺序固定，便于 extractor 解析
"""

SYSTEM_PROMPT = """你是一个深度产品体验分析师。你正在体验下面这个产品：

产品: {product_name}
入口 URL: {product_url}
是否需要登录: {requires_login}

你可以使用以下工具：
- navigate(url): 跳转到 URL，返回标题与最终 URL
- click(selector): 点击 CSS selector 匹配的元素
- extract_visible_text(): 返回当前页面正文（前 4000 字）
- take_screenshot(name): 截图当前页，返回相对路径
- try_google_login(): 在当前页找 'Sign in with Google' 按钮并点击，返回 true/false

工作流（**严格按顺序**）：
1. navigate 到入口 URL
2. take_screenshot('landing')
3. extract_visible_text() 判断这个产品是做什么的
4. 如果 requires_login=true，调一次 try_google_login()
   - 返回 true：你已登录，可以进入产品内部探索更深的页面
   - 返回 false：跳过登录后续，**只**探索可公开访问的营销/文档页
5. 找出主导航里 3-6 个最有信息量的链接（features / pricing / docs / blog / about），
   逐个 navigate + take_screenshot(<页名>) + extract_visible_text 看内容
6. 输出最终报告（**纯 markdown**，**严格按下面字段顺序**，不要加额外章节）：

```
# 产品体验报告

## 概览
<2-4 句中文，说明产品在做什么，目标用户是谁>

## 登录情况
<google | none | failed | skipped>

## 功能盘点
- <功能名>: <在哪发现的页面 / 入口> | <一句话备注>
- <功能名>: <在哪发现的页面 / 入口> | <一句话备注>
(列 4-10 条)

## 优点
<3-6 句，列举亮点。突出竞品上没有的、UI/UX 做得好的、流程顺的点>

## 缺点
<3-6 句，列举体验问题。延迟/卡顿、信息架构混乱、文案不清、隐藏功能、强制注册等>

## 商业模式
<免费 + 订阅 / 一次性付费 / 企业销售 / 广告 / 其它，并写出推断依据>

## 目标用户
<2-3 句，画一个你认为 ICP 的用户像>

## 综合体验分
<0-100 整数>
```

铁律：
- 不要瞎编你没看到的功能。所有"功能盘点"必须基于你 navigate 过 / extract_visible_text 看到过的内容。
- 如果某一步报错，记下来继续推进，不要无限重试同一个 selector。
- 整个 session 最多 25 步操作。超过 20 步还没产出报告就停下输出当前状态作为部分报告。
"""
```

- [ ] **Step 2: 验证 import**

Run: `cd backend && python -c "from src.product_experience.prompts import SYSTEM_PROMPT; assert '产品体验报告' in SYSTEM_PROMPT; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 提交**

```bash
git add backend/src/product_experience/prompts.py
git commit -m "feat(product-experience): system prompt"
```

---

### Task 11: 报告解析器

**Files:**
- Create: `backend/src/product_experience/extractor.py`
- Create: `backend/tests/test_product_experience/test_extractor.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_product_experience/test_extractor.py
from src.product_experience.extractor import ParsedReport, parse_agent_report


SAMPLE = """# 产品体验报告

## 概览
Toolify 是一个 AI 工具目录站。面向想找 AI 工具的从业者。

## 登录情况
google

## 功能盘点
- 工具搜索: 顶部 search bar | 支持中文关键字
- 排行榜: /ranking 页 | 按访问量排
- 新品提交: /submit 页 | 需要登录

## 优点
信息密度高。中文支持好。响应快。

## 缺点
搜索结果排序逻辑不透明。免费档广告偶尔挡住操作区。

## 商业模式
免费 + Pro 订阅。Pro 解锁更详细的 traffic 数据。

## 目标用户
做 AI 应用的独立开发者、AI 内容创作者。

## 综合体验分
72
"""


def test_parse_extracts_all_sections():
    r = parse_agent_report(SAMPLE)
    assert isinstance(r, ParsedReport)
    assert "Toolify" in (r.summary_zh or "")
    assert r.login_used == "google"
    assert r.overall_ux_score == 72.0
    assert len(r.feature_inventory) == 3
    assert r.feature_inventory[0]["name"] == "工具搜索"
    assert "信息密度" in (r.strengths or "")
    assert "搜索结果排序" in (r.weaknesses or "")
    assert "订阅" in (r.monetization_model or "")


def test_parse_returns_partial_when_score_missing():
    bad = SAMPLE.replace("## 综合体验分\n72\n", "")
    r = parse_agent_report(bad)
    assert r.overall_ux_score is None
    assert r.summary_zh is not None  # 其它字段还在
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_product_experience/test_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: 实现解析器**

```python
# backend/src/product_experience/extractor.py
"""把 agent 输出的 markdown 报告解析成 ParsedReport dataclass。

容错优先 —— 任意 section 缺失都允许（写 None / 空 list），不抛异常。
scheduler 调用方再决定如何把 ParsedReport 落表。
"""
import re
from dataclasses import dataclass, field
from typing import Any


SECTION_RE = re.compile(r"^##\s+(.+?)$", re.MULTILINE)


@dataclass
class ParsedReport:
    summary_zh: str | None = None
    login_used: str | None = None
    feature_inventory: list[dict[str, Any]] = field(default_factory=list)
    strengths: str | None = None
    weaknesses: str | None = None
    monetization_model: str | None = None
    target_user: str | None = None
    overall_ux_score: float | None = None


def _split_sections(md: str) -> dict[str, str]:
    """返回 {section_title_normalized: section_body_text}。"""
    matches = list(SECTION_RE.finditer(md))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        out[title] = md[start:end].strip()
    return out


def _parse_feature_inventory(body: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        rest = line.lstrip("-").strip()
        # 期望 "<name>: <where> | <notes>"
        name, sep, after = rest.partition(":")
        if not sep:
            items.append({"name": rest, "where_found": "", "notes": ""})
            continue
        where, sep2, notes = after.strip().partition("|")
        items.append(
            {
                "name": name.strip(),
                "where_found": where.strip(),
                "notes": notes.strip() if sep2 else "",
            }
        )
    return items


def _parse_score(body: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", body)
    if not m:
        return None
    try:
        v = float(m.group(0))
    except ValueError:
        return None
    return max(0.0, min(100.0, v))


def parse_agent_report(md: str) -> ParsedReport:
    sections = _split_sections(md)
    return ParsedReport(
        summary_zh=sections.get("概览") or None,
        login_used=(sections.get("登录情况") or "").splitlines()[0].strip().lower() or None
        if sections.get("登录情况")
        else None,
        feature_inventory=_parse_feature_inventory(sections.get("功能盘点", "")),
        strengths=sections.get("优点") or None,
        weaknesses=sections.get("缺点") or None,
        monetization_model=sections.get("商业模式") or None,
        target_user=sections.get("目标用户") or None,
        overall_ux_score=_parse_score(sections.get("综合体验分", "")),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_product_experience/test_extractor.py -v`
Expected: 2 passed.

- [ ] **Step 5: 提交**

```bash
git add backend/src/product_experience/extractor.py backend/tests/test_product_experience/test_extractor.py
git commit -m "feat(product-experience): markdown report extractor"
```

---

### Task 12: LangGraph 装配

**Files:**
- Create: `backend/src/product_experience/graph.py`

- [ ] **Step 1: 实现 graph**

```python
# backend/src/product_experience/graph.py
"""把 BrowserSession + tools + prompts 装配成一次产品体验 run。

调用方式（scheduler 用）：
    result = await run_experience_agent(target, report_id, screenshot_root)
    # result.markdown / result.trace / result.login_status
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from src.product_experience.browser import BrowserSession
from src.product_experience.google_login import try_google_login
from src.product_experience.prompts import SYSTEM_PROMPT
from src.product_experience.registry import ProductTarget
from src.product_experience.tools import (
    BrowserToolDeps,
    click,
    extract_visible_text,
    navigate,
    take_screenshot,
)

logger = structlog.get_logger()

DEFAULT_SCREENSHOT_ROOT = (
    Path(__file__).resolve().parent.parent.parent / "data" / "product_screenshots"
)


@dataclass
class ExperienceRunResult:
    markdown: str
    login_status: str  # google | none | failed | skipped
    screenshots: list[dict[str, Any]]
    trace: dict[str, Any]


def _build_tools(deps: BrowserToolDeps) -> list[StructuredTool]:
    """绑定 deps.page 进闭包供 LLM 调用。"""

    async def _navigate(url: str) -> str:
        return await navigate(deps.page, url)

    async def _click(selector: str) -> str:
        return await click(deps.page, selector)

    async def _extract() -> str:
        return await extract_visible_text(deps.page)

    async def _screenshot(name: str) -> str:
        rel = await take_screenshot(deps.page, deps, name=name)
        deps.__dict__.setdefault("_shots", []).append(
            {"name": name, "path": rel, "taken_at": datetime.now(tz=timezone.utc)}
        )
        return rel

    async def _try_google_login() -> str:
        ok = await try_google_login(deps.page)
        deps.__dict__["_login_status"] = "google" if ok else "failed"
        return "true" if ok else "false"

    return [
        StructuredTool.from_function(coroutine=_navigate, name="navigate", description="navigate(url)"),
        StructuredTool.from_function(coroutine=_click, name="click", description="click(selector)"),
        StructuredTool.from_function(coroutine=_extract, name="extract_visible_text", description="extract visible text from current page"),
        StructuredTool.from_function(coroutine=_screenshot, name="take_screenshot", description="take_screenshot(name)"),
        StructuredTool.from_function(coroutine=_try_google_login, name="try_google_login", description="try clicking Sign-in-with-Google button"),
    ]


async def run_experience_agent(
    target: ProductTarget,
    report_id: str,
    screenshot_root: Path = DEFAULT_SCREENSHOT_ROOT,
    headless: bool = True,
    recursion_limit: int = 30,
) -> ExperienceRunResult:
    deps = BrowserToolDeps(report_id=report_id, screenshot_root=screenshot_root)
    deps.__dict__["_shots"] = []
    deps.__dict__["_login_status"] = "skipped" if not target.requires_login else "none"

    session = BrowserSession(headless=headless)
    async with session.open() as ctx:
        page = await ctx.new_page()
        deps.page = page

        llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
        tools = _build_tools(deps)
        agent = create_react_agent(llm, tools)

        prompt = SYSTEM_PROMPT.format(
            product_name=target.name,
            product_url=target.url,
            requires_login=str(target.requires_login).lower(),
        )
        messages = [SystemMessage(content=prompt), HumanMessage(content="开始体验。")]
        state = await agent.ainvoke(
            {"messages": messages},
            config={"recursion_limit": recursion_limit},
        )

        final = state["messages"][-1].content
        markdown = final if isinstance(final, str) else str(final)

    trace = {
        "messages": [
            {"role": getattr(m, "type", "?"), "content": str(m.content)[:2000]}
            for m in state["messages"]
        ]
    }
    return ExperienceRunResult(
        markdown=markdown,
        login_status=deps.__dict__["_login_status"],
        screenshots=[
            {"name": s["name"], "path": s["path"], "taken_at": s["taken_at"].isoformat()}
            for s in deps.__dict__["_shots"]
        ],
        trace=trace,
    )
```

- [ ] **Step 2: 验证 import 不报错**

Run: `cd backend && python -c "from src.product_experience.graph import run_experience_agent; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 提交**

```bash
git add backend/src/product_experience/graph.py
git commit -m "feat(product-experience): langgraph react agent assembly"
```

---

### Task 13: Settings 增配

**Files:**
- Modify: `backend/src/config.py`

- [ ] **Step 1: 加配置项**

在 `Settings` 类里 `analysis_interval_minutes` 之后追加：

```python
    experience_interval_minutes: int = 360  # 6 小时一次
    experience_headless: bool = True
```

- [ ] **Step 2: 验证**

Run: `cd backend && AI_IDEA_FINDER_SKIP_KEY_CHECK=1 python -c "from src.config import Settings; s=Settings(); print(s.experience_interval_minutes, s.experience_headless)"`
Expected: `360 True`

- [ ] **Step 3: 提交**

```bash
git add backend/src/config.py
git commit -m "feat(product-experience): settings for cron interval + headless"
```

---

### Task 14: Scheduler job

**Files:**
- Modify: `backend/src/scheduler/jobs.py`
- Create: `backend/tests/test_scheduler_experience.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_scheduler_experience.py
"""验证 _run_experience_impl 选最久未跑的目标、把结果落库。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from src.models.product_experience_report import ProductExperienceReport
from src.scheduler.jobs import _run_experience_impl


@pytest.mark.asyncio
async def test_picks_target_never_run_before(async_session_factory):
    """当 product_experience_reports 表为空时应该选第一个 target。"""
    fake_result = type(
        "R",
        (),
        {
            "markdown": "# 产品体验报告\n\n## 概览\nx\n\n## 综合体验分\n80\n",
            "login_status": "google",
            "screenshots": [],
            "trace": {"messages": []},
        },
    )()
    with patch(
        "src.scheduler.jobs.run_experience_agent",
        new=AsyncMock(return_value=fake_result),
    ) as mock_run:
        await _run_experience_impl(async_session_factory)
        mock_run.assert_awaited_once()
        called_target = mock_run.await_args.args[0]
        assert called_target.slug in {"producthunt", "toolify", "traffic-cv"}

    async with async_session_factory() as s:
        from sqlalchemy import select

        rows = (await s.execute(select(ProductExperienceReport))).scalars().all()
        assert len(rows) == 1
        assert rows[0].overall_ux_score == 80.0
        assert rows[0].login_used == "google"
        assert UUID(str(rows[0].id))
```

(假设项目 `tests/conftest.py` 已经提供 `async_session_factory` fixture；如果没有，先在 `tests/conftest.py` 里参照现有 `test_models.py` 的 setup 加一个。)

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_scheduler_experience.py -v`
Expected: FAIL with `ImportError: cannot import name '_run_experience_impl' from 'src.scheduler.jobs'`.

- [ ] **Step 3: 实现 job**

在 `backend/src/scheduler/jobs.py` 末尾追加（imports 区也要加：`from sqlalchemy import select`、`from src.models.product_experience_report import ProductExperienceReport`、`from src.product_experience.registry import PRODUCT_TARGETS`、`from src.product_experience.graph import run_experience_agent`、`from src.product_experience.extractor import parse_agent_report`、`import asyncio`、`from uuid import uuid4`）：

```python
async def _run_experience_impl(session_factory) -> None:
    """挑一个最久未跑过的 target 跑一次产品体验，落 product_experience_reports 一行。"""
    async with session_factory() as session:
        # 取每个 slug 的最近一次 run_started_at
        rows = (
            await session.execute(
                select(
                    ProductExperienceReport.product_slug,
                    ProductExperienceReport.run_started_at,
                ).order_by(ProductExperienceReport.run_started_at.desc())
            )
        ).all()
        latest_per_slug: dict[str, datetime] = {}
        for slug, ts in rows:
            latest_per_slug.setdefault(slug, ts)

    # 找一个从没跑过的；都跑过则挑 latest_per_slug 里最旧的
    targets = list(PRODUCT_TARGETS)
    never_run = [t for t in targets if t.slug not in latest_per_slug]
    if never_run:
        target = never_run[0]
    else:
        target = min(targets, key=lambda t: latest_per_slug[t.slug])

    started = datetime.now(tz=timezone.utc)
    report_id = str(uuid4())
    status = "completed"
    failure_reason: str | None = None
    parsed = None
    run_result = None
    try:
        run_result = await asyncio.wait_for(
            run_experience_agent(target, report_id=report_id),
            timeout=480,  # 8 分钟硬上限
        )
        parsed = parse_agent_report(run_result.markdown)
    except TimeoutError:
        status = "failed"
        failure_reason = "agent run timed out after 480s"
        logger.warning("experience_timeout", slug=target.slug)
    except Exception as e:
        status = "failed"
        failure_reason = f"{type(e).__name__}: {e}"
        logger.exception("experience_failed", slug=target.slug)

    completed = datetime.now(tz=timezone.utc)

    async with session_factory() as session:
        row = ProductExperienceReport(
            id=UUID(report_id),
            product_slug=target.slug,
            product_url=target.url,
            product_name=target.name,
            run_started_at=started,
            run_completed_at=completed,
            status=status,
            failure_reason=failure_reason,
            login_used=(run_result.login_status if run_result else "skipped"),
            overall_ux_score=parsed.overall_ux_score if parsed else None,
            summary_zh=parsed.summary_zh if parsed else None,
            feature_inventory=parsed.feature_inventory if parsed else None,
            strengths=parsed.strengths if parsed else None,
            weaknesses=parsed.weaknesses if parsed else None,
            monetization_model=parsed.monetization_model if parsed else None,
            target_user=parsed.target_user if parsed else None,
            screenshots=run_result.screenshots if run_result else None,
            agent_trace=run_result.trace if run_result else None,
        )
        session.add(row)
        await session.commit()
```

import 部分顶部追加：

```python
import asyncio
from datetime import timezone
from uuid import UUID, uuid4

from sqlalchemy import select

from src.models.product_experience_report import ProductExperienceReport
from src.product_experience.extractor import parse_agent_report
from src.product_experience.graph import run_experience_agent
from src.product_experience.registry import PRODUCT_TARGETS
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_scheduler_experience.py -v`
Expected: 1 passed.

- [ ] **Step 5: 注册 cron**

找到 `backend/src/scheduler/jobs.py` 里启动 scheduler 时 `add_job` 的代码段（已有 `collect_data` / `process_data` / `analyze_data` 三个 job）。仿照同样模式追加：

```python
scheduler.add_job(
    _run_experience_with_record,
    trigger="interval",
    minutes=settings.experience_interval_minutes,
    id="experience_products",
    next_run_time=datetime.utcnow(),
    max_instances=1,
    coalesce=True,
    misfire_grace_time=600,
)
```

并定义 wrapper（参考其它 `_run_xxx_with_record`）：

```python
async def _run_experience_with_record(session_factory) -> None:
    job_id = "experience_products"
    if not mark_scheduled_running(job_id):
        logger.info("experience_skip_already_running")
        return
    record_start(job_id)
    error: str | None = None
    try:
        await _run_experience_impl(session_factory)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        raise
    finally:
        record_finish(job_id, error=error)
        clear_scheduled_running(job_id)
```

- [ ] **Step 6: 跑现有 scheduler 测试确保没回归**

Run: `cd backend && pytest tests/test_scheduler.py -v`
Expected: 全部通过（数量与之前一致）。

- [ ] **Step 7: 提交**

```bash
git add backend/src/scheduler/jobs.py backend/tests/test_scheduler_experience.py
git commit -m "feat(product-experience): scheduler cron + selection logic"
```

---

### Task 15: API 列表 + 详情

**Files:**
- Create: `backend/src/api/product_experience_reports.py`
- Create: `backend/tests/test_api/test_product_experience_reports.py`
- Modify: `backend/src/api/router.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_api/test_product_experience_reports.py
from datetime import datetime, timezone
from uuid import uuid4

import pytest


async def _make_row(session, **overrides):
    from src.models.product_experience_report import ProductExperienceReport

    defaults = dict(
        id=uuid4(),
        product_slug="toolify",
        product_url="https://www.toolify.ai",
        product_name="Toolify",
        run_started_at=datetime.now(tz=timezone.utc),
        run_completed_at=datetime.now(tz=timezone.utc),
        status="completed",
        failure_reason=None,
        login_used="google",
        overall_ux_score=72.0,
        summary_zh="一个 AI 工具目录站",
        feature_inventory=[{"name": "搜索", "where_found": "顶栏", "notes": ""}],
        strengths="信息密度高",
        weaknesses="排序不透明",
        monetization_model="免费 + Pro",
        target_user="独立开发者",
        screenshots=[{"name": "landing", "path": "x/landing.png", "taken_at": "2026-04-23T00:00:00+00:00"}],
        agent_trace={"messages": []},
    )
    defaults.update(overrides)
    row = ProductExperienceReport(**defaults)
    session.add(row)
    await session.commit()
    return row


@pytest.mark.asyncio
async def test_list_returns_envelope_with_items(client, async_session_factory):
    async with async_session_factory() as s:
        await _make_row(s)
    resp = await client.get("/api/product-experience-reports")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "000000"
    assert body["data"]["total"] == 1
    assert body["data"]["items"][0]["product_slug"] == "toolify"
    assert body["data"]["items"][0]["screenshots_count"] == 1


@pytest.mark.asyncio
async def test_detail_returns_full_row(client, async_session_factory):
    async with async_session_factory() as s:
        row = await _make_row(s)
    resp = await client.get(f"/api/product-experience-reports/{row.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["agent_trace"] == {"messages": []}
    assert body["data"]["overall_ux_score"] == 72.0


@pytest.mark.asyncio
async def test_detail_returns_404_for_unknown_id(client):
    resp = await client.get(f"/api/product-experience-reports/{uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "PEX001"


@pytest.mark.asyncio
async def test_detail_returns_400_for_malformed_uuid(client):
    resp = await client.get("/api/product-experience-reports/not-a-uuid")
    assert resp.status_code == 400
    assert resp.json()["code"] == "PEX002"
```

(`client` / `async_session_factory` fixtures 沿用项目 `tests/conftest.py` 已有的。)

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_api/test_product_experience_reports.py -v`
Expected: 4 FAIL（路由 404）。

- [ ] **Step 3: 在 exceptions.py 里加错误码**

打开 `backend/src/exceptions.py`，在 `ErrorCode` 枚举里追加：

```python
PEX001 = ("PEX001", "product experience report not found")
PEX002 = ("PEX002", "invalid product experience report id")
```

- [ ] **Step 4: 实现路由**

```python
# backend/src/api/product_experience_reports.py
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.exceptions import APIError, ErrorCode
from src.models.product_experience_report import ProductExperienceReport
from src.schemas.product_experience_report import (
    ProductExperienceListResponse,
    ProductExperienceReportListOut,
    ProductExperienceReportOut,
)

logger = structlog.get_logger()
router = APIRouter()


@router.get("/product-experience-reports", response_model=ProductExperienceListResponse)
async def list_reports(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    product_slug: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> ProductExperienceListResponse:
    base = select(ProductExperienceReport)
    if product_slug:
        base = base.where(ProductExperienceReport.product_slug == product_slug)

    total = (await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    rows = (
        await session.execute(
            base.order_by(ProductExperienceReport.run_started_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()

    items = [
        ProductExperienceReportListOut(
            id=r.id,
            product_slug=r.product_slug,
            product_name=r.product_name,
            product_url=r.product_url,
            run_completed_at=r.run_completed_at,
            status=r.status,
            login_used=r.login_used,
            overall_ux_score=r.overall_ux_score,
            summary_zh=r.summary_zh,
            screenshots_count=len(r.screenshots) if r.screenshots else 0,
        )
        for r in rows
    ]
    return ProductExperienceListResponse(
        items=items, total=total, page=page, per_page=per_page
    )


@router.get(
    "/product-experience-reports/{report_id}",
    response_model=ProductExperienceReportOut,
)
async def get_report(
    report_id: str,
    session: AsyncSession = Depends(get_session),
) -> ProductExperienceReportOut:
    try:
        rid = UUID(report_id)
    except ValueError:
        raise APIError(ErrorCode.PEX002, status_code=400)
    row = (
        await session.execute(
            select(ProductExperienceReport).where(ProductExperienceReport.id == rid)
        )
    ).scalar_one_or_none()
    if row is None:
        raise APIError(ErrorCode.PEX001, status_code=404)
    return ProductExperienceReportOut.model_validate(row)
```

- [ ] **Step 5: 注册到 router**

修改 `backend/src/api/router.py`：

```python
from src.api.product_experience_reports import router as product_experience_router
# ...
api_router.include_router(product_experience_router)
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && pytest tests/test_api/test_product_experience_reports.py -v`
Expected: 4 passed.

- [ ] **Step 7: 提交**

```bash
git add backend/src/api/product_experience_reports.py backend/src/api/router.py backend/src/exceptions.py backend/tests/test_api/test_product_experience_reports.py
git commit -m "feat(product-experience): list + detail API endpoints"
```

---

### Task 16: Pipeline trigger 加 experience_products

**Files:**
- Modify: `backend/src/api/pipeline.py`

- [ ] **Step 1: 增加 inline 触发分支**

在 `pipeline.py` 里 `JOB_HANDLERS` / 调度任务白名单（具体看现有写法）里加 `experience_products`。让 `POST /api/pipeline/trigger/experience_products` 走 scheduler `modify(next_run_time=now)` 路径，与 `collect_data` / `process_data` / `analyze_data` 一致。

具体：在白名单常量里追加 `"experience_products"`（搜索 `_RUNNING_KEY_ALIASES` 上下文找到对应集合）。

- [ ] **Step 2: 加测试**

在 `backend/tests/test_api/test_pipeline.py`（或现有同类文件）里追加：

```python
@pytest.mark.asyncio
async def test_trigger_experience_products_returns_202(client):
    resp = await client.post("/api/pipeline/trigger/experience_products")
    assert resp.status_code in (200, 202)
    assert resp.json()["code"] == "000000"
```

- [ ] **Step 3: 跑测试**

Run: `cd backend && pytest tests/test_api/test_pipeline.py -v`
Expected: 通过且无回归。

- [ ] **Step 4: 提交**

```bash
git add backend/src/api/pipeline.py backend/tests/test_api/test_pipeline.py
git commit -m "feat(product-experience): pipeline trigger for experience_products"
```

---

### Task 17: 静态目录挂载

**Files:**
- Modify: `backend/src/main.py`

- [ ] **Step 1: 在 FastAPI app 上挂截图静态目录**

打开 `backend/src/main.py`，在创建 `app = FastAPI(...)` 之后、`app.include_router(api_router)` 之前追加：

```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles

_screenshot_dir = Path(__file__).resolve().parent.parent / "data" / "product_screenshots"
_screenshot_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/static/screenshots",
    StaticFiles(directory=str(_screenshot_dir)),
    name="product-screenshots",
)
```

- [ ] **Step 2: 启动 backend 验证**

```bash
cd backend && PYTHONPATH=. python -c "
from src.main import app
routes = [r.path for r in app.routes]
assert any('/static/screenshots' in r for r in routes), routes
print('mount ok')
"
```

Expected: `mount ok`

- [ ] **Step 3: 提交**

```bash
git add backend/src/main.py
git commit -m "feat(product-experience): mount /static/screenshots"
```

---

### Task 18: 前端类型 + API 封装

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: 加类型**

在 `types.ts` 末尾追加：

```ts
export interface ProductExperienceReportListItem {
  id: string;
  product_slug: string;
  product_name: string;
  product_url: string;
  run_completed_at: string | null;
  status: "completed" | "partial" | "failed";
  login_used: "google" | "none" | "failed" | "skipped";
  overall_ux_score: number | null;
  summary_zh: string | null;
  screenshots_count: number;
}

export interface FeatureInventoryItem {
  name: string;
  where_found: string;
  notes: string;
}

export interface ScreenshotEntry {
  name: string;
  path: string;
  taken_at: string;
}

export interface ProductExperienceReport {
  id: string;
  product_slug: string;
  product_url: string;
  product_name: string;
  run_started_at: string;
  run_completed_at: string | null;
  status: "completed" | "partial" | "failed";
  failure_reason: string | null;
  login_used: "google" | "none" | "failed" | "skipped";
  overall_ux_score: number | null;
  summary_zh: string | null;
  feature_inventory: FeatureInventoryItem[] | null;
  strengths: string | null;
  weaknesses: string | null;
  monetization_model: string | null;
  target_user: string | null;
  screenshots: ScreenshotEntry[] | null;
  agent_trace: Record<string, unknown> | null;
  created_at: string;
}

export interface ProductExperienceListResponse {
  items: ProductExperienceReportListItem[];
  total: number;
  page: number;
  per_page: number;
}
```

- [ ] **Step 2: 加 API fetcher**

在 `api.ts` 末尾追加：

```ts
import type {
  ProductExperienceListResponse,
  ProductExperienceReport,
} from "./types";

export async function listProductExperienceReports(params: {
  page?: number;
  per_page?: number;
  product_slug?: string;
}): Promise<ProductExperienceListResponse> {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.per_page) qs.set("per_page", String(params.per_page));
  if (params.product_slug) qs.set("product_slug", params.product_slug);
  return apiGet<ProductExperienceListResponse>(
    `/api/product-experience-reports?${qs}`,
  );
}

export async function getProductExperienceReport(
  id: string,
): Promise<ProductExperienceReport> {
  return apiGet<ProductExperienceReport>(
    `/api/product-experience-reports/${id}`,
  );
}
```

(注意：`apiGet` 是项目现有 helper；如果项目用的是别的命名比如 `fetchJson`，按现有命名替换。)

- [ ] **Step 3: typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 error.

- [ ] **Step 4: 提交**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts
git commit -m "feat(product-experience): frontend types + api fetchers"
```

---

### Task 19: 截图画廊组件

**Files:**
- Create: `frontend/src/components/screenshot-gallery.tsx`

- [ ] **Step 1: 实现组件**

```tsx
// frontend/src/components/screenshot-gallery.tsx
"use client";

import Image from "next/image";
import { useState } from "react";
import type { ScreenshotEntry } from "@/lib/types";

const STATIC_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:53839";

export function ScreenshotGallery({ shots }: { shots: ScreenshotEntry[] }) {
  const [active, setActive] = useState<ScreenshotEntry | null>(null);
  if (!shots || shots.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="product-detail-screenshots-empty">
        本次体验没有截图
      </p>
    );
  }
  return (
    <div data-testid="product-detail-screenshots">
      <div className="grid grid-cols-3 gap-3">
        {shots.map((s) => (
          <button
            key={s.path}
            onClick={() => setActive(s)}
            className="relative aspect-video overflow-hidden rounded-md border hover:ring-2 hover:ring-primary/40"
            data-testid={`product-detail-screenshot-${s.name}`}
          >
            <Image
              src={`${STATIC_BASE}/static/screenshots/${s.path}`}
              alt={s.name}
              fill
              sizes="(max-width: 768px) 33vw, 200px"
              className="object-cover"
              unoptimized
            />
            <span className="absolute bottom-0 left-0 right-0 bg-black/50 text-white text-[11px] px-1 py-0.5 truncate">
              {s.name}
            </span>
          </button>
        ))}
      </div>
      {active && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-8"
          onClick={() => setActive(null)}
        >
          <Image
            src={`${STATIC_BASE}/static/screenshots/${active.path}`}
            alt={active.name}
            width={1280}
            height={720}
            className="max-h-full max-w-full object-contain"
            unoptimized
          />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 error.

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/screenshot-gallery.tsx
git commit -m "feat(product-experience): screenshot gallery component"
```

---

### Task 20: 列表卡片 + 列表页

**Files:**
- Create: `frontend/src/components/product-experience-card.tsx`
- Create: `frontend/src/app/products/page.tsx`

- [ ] **Step 1: 实现卡片**

```tsx
// frontend/src/components/product-experience-card.tsx
import Link from "next/link";
import type { ProductExperienceReportListItem } from "@/lib/types";

const LOGIN_LABEL: Record<string, string> = {
  google: "已用 Google 登录",
  failed: "登录失败",
  none: "未登录",
  skipped: "无需登录",
};

export function ProductExperienceCard({
  item,
}: {
  item: ProductExperienceReportListItem;
}) {
  return (
    <Link
      href={`/products/${item.id}`}
      className="block rounded-2xl bg-card px-5 py-4 hover:ring-2 hover:ring-primary/30 transition"
      style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
      data-testid={`product-experience-card-${item.product_slug}`}
    >
      <div className="flex items-baseline justify-between">
        <h3 className="text-lg font-medium">{item.product_name}</h3>
        <span className="text-2xl font-mono">
          {item.overall_ux_score?.toFixed(0) ?? "—"}
        </span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{item.product_url}</p>
      {item.summary_zh && (
        <p className="mt-3 text-sm leading-relaxed line-clamp-3">{item.summary_zh}</p>
      )}
      <div className="mt-3 flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{LOGIN_LABEL[item.login_used] ?? item.login_used}</span>
        <span>{item.run_completed_at ? new Date(item.run_completed_at).toLocaleString("zh-CN") : "进行中"}</span>
      </div>
    </Link>
  );
}
```

- [ ] **Step 2: 实现列表页**

```tsx
// frontend/src/app/products/page.tsx
import { listProductExperienceReports } from "@/lib/api";
import { ProductExperienceCard } from "@/components/product-experience-card";

export const dynamic = "force-dynamic";

export default async function ProductsPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string; product_slug?: string }>;
}) {
  const sp = await searchParams;
  const page = Number(sp.page ?? 1);
  const data = await listProductExperienceReports({
    page,
    per_page: 20,
    product_slug: sp.product_slug,
  });

  return (
    <div className="space-y-6" data-testid="products-list">
      <header>
        <h1 className="text-2xl font-medium">产品体验报告</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Agent 真实访问产品网站、深度体验后产出的结构化报告
        </p>
      </header>

      {data.items.length === 0 ? (
        <p className="text-muted-foreground" data-testid="products-list-empty">
          还没有产品体验报告。后台 cron 会按 6 小时间隔逐个跑，或在仪表盘手动触发。
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {data.items.map((item) => (
            <ProductExperienceCard key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: typecheck + lint**

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: 0 error.

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/product-experience-card.tsx frontend/src/app/products/page.tsx
git commit -m "feat(product-experience): list page + card"
```

---

### Task 21: 详情页 + not-found

**Files:**
- Create: `frontend/src/app/products/[id]/page.tsx`
- Create: `frontend/src/app/products/not-found.tsx`

- [ ] **Step 1: 实现详情页**

```tsx
// frontend/src/app/products/[id]/page.tsx
import { notFound } from "next/navigation";
import { getProductExperienceReport } from "@/lib/api";
import { ScreenshotGallery } from "@/components/screenshot-gallery";
import { ApiError } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ProductDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let report;
  try {
    report = await getProductExperienceReport(id);
  } catch (e) {
    if (e instanceof ApiError && (e.code === "PEX001" || e.code === "PEX002")) {
      notFound();
    }
    throw e;
  }

  return (
    <article className="space-y-8" data-testid="product-detail">
      <header>
        <h1 className="text-2xl font-medium">{report.product_name}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          <a
            href={report.product_url}
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
            data-testid="product-detail-open-original"
          >
            {report.product_url} ↗
          </a>
        </p>
        <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span>状态: {report.status}</span>
          <span>登录: {report.login_used}</span>
          <span>
            体验分:{" "}
            <span className="text-foreground font-mono">
              {report.overall_ux_score?.toFixed(0) ?? "—"}
            </span>
          </span>
          <span>
            完成于:{" "}
            {report.run_completed_at
              ? new Date(report.run_completed_at).toLocaleString("zh-CN")
              : "—"}
          </span>
        </div>
      </header>

      {report.failure_reason && (
        <section className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
          ⚠ 本次运行失败：{report.failure_reason}
        </section>
      )}

      <Section title="概览">{report.summary_zh ?? "—"}</Section>

      <section>
        <h2 className="text-base font-medium mb-2">功能盘点</h2>
        {report.feature_inventory && report.feature_inventory.length > 0 ? (
          <ul className="space-y-2 text-sm">
            {report.feature_inventory.map((f, i) => (
              <li key={i} className="border-l-2 border-primary/40 pl-3">
                <div className="font-medium">{f.name}</div>
                {f.where_found && (
                  <div className="text-xs text-muted-foreground">{f.where_found}</div>
                )}
                {f.notes && <div className="text-xs">{f.notes}</div>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">—</p>
        )}
      </section>

      <Section title="优点">{report.strengths ?? "—"}</Section>
      <Section title="缺点">{report.weaknesses ?? "—"}</Section>
      <Section title="商业模式">{report.monetization_model ?? "—"}</Section>
      <Section title="目标用户">{report.target_user ?? "—"}</Section>

      <section>
        <h2 className="text-base font-medium mb-2">截图</h2>
        <ScreenshotGallery shots={report.screenshots ?? []} />
      </section>

      <section>
        <h2 className="text-base font-medium mb-2">Agent 推理轨迹</h2>
        {report.agent_trace ? (
          <details>
            <summary className="cursor-pointer text-sm text-muted-foreground">
              展开（{Object.keys(report.agent_trace).length} 字段）
            </summary>
            <pre
              className="mt-2 text-[11px] bg-muted p-3 rounded-md overflow-x-auto"
              data-testid="product-detail-trace"
            >
              {(() => {
                try {
                  return JSON.stringify(report.agent_trace, null, 2);
                } catch {
                  return "（轨迹数据损坏）";
                }
              })()}
            </pre>
          </details>
        ) : (
          <p className="text-sm text-muted-foreground" data-testid="product-detail-trace-missing">
            此分析无推理轨迹
          </p>
        )}
      </section>
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-base font-medium mb-2">{title}</h2>
      <p className="text-sm leading-relaxed whitespace-pre-line">{children}</p>
    </section>
  );
}
```

- [ ] **Step 2: 实现 not-found**

```tsx
// frontend/src/app/products/not-found.tsx
export default function ProductNotFound() {
  return (
    <div data-testid="product-not-found" className="text-center py-20">
      <h1 className="text-xl font-medium">没找到这份产品体验报告</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        可能这份 ID 无效，或者它已经被清理。
      </p>
    </div>
  );
}
```

- [ ] **Step 3: typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: 0 error.

- [ ] **Step 4: 提交**

```bash
git add frontend/src/app/products/
git commit -m "feat(product-experience): detail page + not-found"
```

---

### Task 22: 侧边栏导航

**Files:**
- Modify: `frontend/src/components/sidebar.tsx`

- [ ] **Step 1: 加导航项**

打开 sidebar.tsx，在已有 `/sources` / `/analysis` 之后追加：

```tsx
{ href: "/products", label: "产品体验", testid: "sidebar-link-products" },
```

(具体写法跟随已有结构 —— 可能是 array of `{href, label}` 对象，或直接 jsx 列表。复用现有模式即可。)

- [ ] **Step 2: 跑 dev server 手测**

```bash
./scripts/start-frontend.sh
```

打开 http://localhost:53840，确认侧栏出现"产品体验"项，点击跳到 `/products`，看到空态文案。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/sidebar.tsx
git commit -m "feat(product-experience): sidebar nav link"
```

---

### Task 23: 端到端冒烟

**Files:** （仅运行验证，不增改代码）

- [ ] **Step 1: 一次性 bootstrap Google profile**

```bash
cd backend && PYTHONPATH=. python scripts/bootstrap_browser_profile.py
```

按提示在打开的 Chrome 窗口里登录你的 Google 账号 → 回到终端按 Enter 关闭。验证 `backend/data/browser_profile/` 出现 cookies 等文件。

- [ ] **Step 2: 启动 backend + frontend**

```bash
./scripts/start-backend.sh &
./scripts/start-frontend.sh &
```

- [ ] **Step 3: 手动触发一次产品体验**

```bash
curl -X POST http://localhost:53839/api/pipeline/trigger/experience_products
```

观察 backend 日志：应当看到 `agent_navigate` / `agent_screenshot` / `google_login_*` 等结构化日志，最终落 `product_experience_reports` 一行。

- [ ] **Step 4: 列表 + 详情 API 验证**

```bash
curl -s http://localhost:53839/api/product-experience-reports | python3 -m json.tool | head -40
```

Expected: `code=000000`，`data.items` 至少 1 条，`product_slug` ∈ {producthunt, toolify, traffic-cv}。

```bash
ID=$(curl -s http://localhost:53839/api/product-experience-reports | python3 -c "import json,sys;print(json.load(sys.stdin)['data']['items'][0]['id'])")
curl -s http://localhost:53839/api/product-experience-reports/$ID | python3 -m json.tool | head -60
```

Expected: 详情含 `feature_inventory` / `strengths` / `screenshots`。

- [ ] **Step 5: 浏览器验证**

打开 http://localhost:53840/products，看到刚才的产品卡片；点进去看到截图画廊（图片应能显示，URL 形如 `http://localhost:53839/static/screenshots/<uuid>/landing-xxxx.png`）。

- [ ] **Step 6: 截止点提交**

```bash
git add docs/superpowers/plans/2026-04-23-product-experience-agent.md
git commit -m "docs: product experience implementation plan"
```

---

## Self-Review

**Spec coverage**：
- 目标站点：Task 1 注册表写死 3 条 ✓
- 体验深度（带 Google 登录）：Task 6 BrowserSession + Task 7 google_login + Task 8 bootstrap 脚本 ✓
- 浏览器栈 = Playwright：Task 6 ✓
- 触发 = 周期 cron：Task 14 `experience_products` job ✓
- 存储 = 新表：Task 2/3 `product_experience_reports` ✓
- 报告字段：Task 4 schema + Task 10 prompt + Task 11 extractor 严格对齐 ✓
- 前端：Task 18-22 ✓
- 一次性 Google 登录如何做：Task 8 bootstrap 脚本 + Context 段落解释了机制 ✓

**Placeholder scan**：所有 step 都给了完整代码或具体命令，未使用 TBD / Similar to Task N。Task 16 / Task 22 涉及"按现有写法追加一行"是 modify 现有文件且模式已被现有代码示范，可接受。

**Type consistency**：
- `ProductTarget.slug` / `.url` / `.name` / `.requires_login`（Task 1）→ Task 12 / Task 14 引用一致 ✓
- `ProductExperienceReport` 列名（Task 2）↔ schema（Task 4）↔ extractor 输出 dict key（Task 11）↔ scheduler 写库（Task 14）↔ API serialization（Task 15）↔ 前端类型（Task 18）↔ 前端组件（Task 19-21）—— 全链路 `feature_inventory` / `strengths` / `weaknesses` / `monetization_model` / `target_user` / `overall_ux_score` / `summary_zh` / `screenshots` / `agent_trace` 命名一致 ✓
- `login_used` 取值集合 `google | none | failed | skipped`：prompt（Task 10）/ scheduler（Task 14）/ 前端 `LOGIN_LABEL`（Task 20）一致 ✓
- 错误码 `PEX001` / `PEX002`：Task 15 测试 + 实现 + Task 21 前端 not-found 触发条件一致 ✓
