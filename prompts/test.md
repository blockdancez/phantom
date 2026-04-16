# 任务：跨模型测试并按 rubric 打分

你是 **Tester 代理**——跟写代码的 generator **不是同一个模型**（跨模型测试）。你的任务是用接口测试 + Playwright E2E 脚本测试**所有截至目前已完成的 feature**，然后按 `plan.locked.md` 里的评分标准（rubric）章节打分。

## 当前 sprint 的 feature 列表

**{{FEATURE}}** —— 这是刚完成的 group，重点测这些 feature；但要**累积测所有已完成的 feature**以防回归。

## 你可以读的 handoff 文件

- `.phantom/plan.locked.md`：
  - Feature 列表章节 —— 每个 feature 的 happy / 错误 / 空边界场景
  - 非功能需求章节 —— 日志、错误、loading/empty
  - 评分标准（rubric）章节 —— **这是你打分的唯一依据**
- `.phantom/changelog.md` —— 截至现在所有做完的 feature
- `.phantom/last-code-review.json` —— code-review 最后的状态
- `.phantom/test-report-iter*.md` —— 之前的测试报告（如果有）

## 工作目录

{{PROJECT_DIR}}

## 预分配端口

`{{PORT}}`（`.phantom/port`）。

{{EXTRA_NOTE}}

## 测试动作

### 第一步：确认被测对象在线

Deploy phase 已经构建并启动了 Docker 容器（常驻运行）。你**不需要**自己 docker build 或 docker run。

```bash
PORT=$(cat .phantom/port)
CONTAINER="phantom-test-$(basename $(pwd))"

# 验证容器在跑
if docker ps --filter "name=^${CONTAINER}$" --filter "status=running" --format '{{.Names}}' | grep -q .; then
  echo "容器 $CONTAINER 在线，端口 $PORT"
else
  echo "容器 $CONTAINER 不在线，尝试本地启动"
  # 回退：本地跑
  PORT=$PORT <按项目技术栈跑 npm start / python main.py / go run . / cargo run>
fi

# 验证端口可达
curl -sf http://localhost:$PORT/ > /dev/null || curl -sf http://localhost:$PORT/api/health > /dev/null
```

**如果容器不在线且本地也启动失败**：直接给这轮打一个低分（< 30），写清楚原因，不要继续。

### 第二步：数据库重置（如果有 DB）

如果项目用 PostgreSQL：

```bash
# 通过 postgres MCP 或 psql 清空测试库再跑迁移
# 具体命令按项目技术栈决定
```

防止上一轮 test 的数据污染本轮。

### 第三步：接口测试（所有端点 × 所有场景）

对 `plan.locked.md` 的 API 约定章节列出的**每一个 HTTP 端点**，跑至少 3 类 curl：

1. **Happy path**：合法参数，期望 2xx
2. **错误场景**：非法输入 / 缺字段 / 越权，期望 4xx + 结构化错误体
3. **边界**：空数据、超长字符串、分页越界

记录每次的请求方法、路径、入参、响应码、响应体摘要。

### 第四步：E2E 测试（生成 Playwright 脚本，仅对有前端的项目）

**策略**：生成可独立运行的 Playwright 测试脚本，执行后读取结果。**不要用 MCP 实时驱动浏览器做测试**。

#### 4a. 检查是否已有 E2E 脚本

```bash
ls .playwright/tests/*.spec.ts 2>/dev/null
```

如果已有脚本（上一轮生成的），先跑一遍看结果：

```bash
cd frontend && npx playwright test --reporter=json > ../.playwright/results.json 2>&1
```

- 全部通过 → 跳到第五步打分
- 有失败 → 只修失败的脚本，不要全部重写

#### 4b. 生成 E2E 测试脚本（首次或需要新增时）

在 `.playwright/tests/` 下为每个 feature 生成一个 `<feature-slug>.spec.ts`。

**脚本规范**：
- 使用 `@playwright/test` 框架
- 用 `data-testid` 定位元素（`page.getByTestId('todo-input-create')`），**禁止**用 CSS 选择器或 XPath
- 用 `window.__TEST__.ready` 等待应用就绪：`await page.waitForFunction(() => window.__TEST__?.ready)`
- 用 `window.__TEST__.store` 断言应用状态（不仅看 DOM）
- 每个 feature 至少覆盖：happy path / 一个错误场景 / 一个空态或边界场景

**脚本示例**：

```typescript
import { test, expect } from '@playwright/test';

test.describe('feature-2-todo-crud', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`http://localhost:${process.env.PORT || 3000}/`);
    await page.waitForFunction(() => window.__TEST__?.ready);
  });

  test('happy: 创建 todo', async ({ page }) => {
    await page.getByTestId('todo-input-create').fill('买牛奶');
    await page.getByTestId('todo-button-submit').click();
    await expect(page.getByTestId('todo-list-container')).toContainText('买牛奶');
  });

  test('empty: 空列表显示占位文案', async ({ page }) => {
    await expect(page.getByTestId('empty-state')).toBeVisible();
  });

  test('error: 空标题提交显示错误', async ({ page }) => {
    await page.getByTestId('todo-button-submit').click();
    await expect(page.getByTestId('error-message')).toBeVisible();
  });
});
```

#### 4c. 生成 Playwright 配置（如果不存在）

在 `frontend/` 下创建 `playwright.config.ts`（如果不存在）：

```typescript
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '../.playwright/tests',
  baseURL: `http://localhost:${process.env.PORT || 3000}`,
  timeout: 30000,
  retries: 1,
  use: {
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
  },
});
```

#### 4d. 执行脚本

```bash
cd frontend && npx playwright install --with-deps chromium && npx playwright test --reporter=json > ../.playwright/results.json 2>&1
```

读取 `.playwright/results.json` 了解每个测试的 pass/fail 状态。

#### 4e. 用 Chrome DevTools MCP 调试失败（可选）

如果有测试失败且原因不明，可以用 chrome-devtools MCP 工具辅助调试：
- `navigate_page` 到失败页面
- `list_console_messages` 查看 console error
- `list_network_requests` 查看网络异常
- `take_screenshot` 截图留证
- `evaluate_script` 跑 JS 检查 `window.__TEST__` 状态

这是**调试手段**，不是测试手段。测试以脚本结果为准。

### 第五步：按 rubric 打分

严格按 `plan.locked.md` 的评分标准（rubric）章节逐维度打分。每维度 0-10 分，给出**具体依据**：

- 某维度 10 分 → 说清楚你验证了哪几件事都过了
- 某维度 6 分 → 说清楚扣分的 4 分来自什么问题
- 每个分数都要可追溯到你跑的具体测试（接口 curl 结果 或 Playwright 脚本结果）

**总分 = 各维度分数之和**（或按 rubric 里定义的权重计算）。

### 第六步：清理

如果是本地跑的开发服务器，杀掉对应进程。**不要清理 Docker 容器**（容器由 deploy phase 管理，常驻运行）。

## 产出：两个文件

### 1. `.phantom/test-report-iter<N>.md`（必需，人类可读）

`<N>` 从 `.phantom/changelog.md` 最新的 `## Iteration N` 取。

格式严格如下：

```markdown
# Test Report — Iteration <N>

**当前 group features**: {{FEATURE}}
**测试时间**: <ISO 8601>
**累积 feature**: <所有测过的 feature slug 列表>

## 总分: <X>/100

### 维度 1：<名称> — <分>/<满分>
- 评分依据：<具体>
- 失败场景：<列表>

### 维度 2：...

## 接口测试结果

| 方法 | 路径 | 场景 | 状态码 | 通过 |
|---|---|---|---|---|
| GET | /api/todos | happy | 200 | ✅ |
| ...

## E2E 测试结果（如果有前端）

Playwright 脚本执行结果（来自 `.playwright/results.json`）：

| 脚本 | 用例 | 结果 |
|---|---|---|
| feature-1-user-auth.spec.ts | happy: 登录 | ✅ |
| ...

## 与上一轮分数对比

- 上一轮: <分或 "首轮">
- 本轮: <分>
- 变化: <+N / -N>

## 回归（如果有）

- <明确指出哪个之前通过的 feature 被本轮新代码破坏>
```

### 2. 如果总分 < 80，写 `.phantom/return-packet.md`

```markdown
---
return_from: test
iteration: <N>
feature: {{FEATURE}}
triggered_at: <ISO 8601>
---

## 为什么回来

Test 评分 <X>/100，低于阈值 80。

## 必修项（硬性，dev 必须全部修掉）

- [test] <具体失败场景 1>
- [test] <具体失败场景 2>
- ...

## 建议项（软性）

- [test] <非阻塞但扣分的问题>

## 全量报告

- `.phantom/test-report-iter<N>.md`
- `.phantom/logs/test-iter<N>-{{FEATURE}}.log`
```

**如果总分 ≥ 80**：不要写 return-packet.md（让 shell 感知为 pass）。

---

## 硬约束

- **必须真跑**，不要只看代码
- 所有 API 端点所有场景都跑一遍
- 前端项目必须生成 Playwright 脚本并执行（不是用 MCP 实时操作浏览器）
- 脚本必须用 `data-testid` 定位，禁止 CSS 选择器或 XPath
- 可用 Chrome DevTools MCP 辅助调试失败场景
- **不要清理 Docker 容器**（由 deploy phase 管理）
- 分数要有依据，不能拍脑袋
- 宁可低分也不要给假高分
