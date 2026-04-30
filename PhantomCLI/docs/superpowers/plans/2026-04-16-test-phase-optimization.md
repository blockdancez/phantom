# Test Phase 优化：AI 生成脚本 + 可测试性改造

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 test phase 从"AI 实时驱动浏览器（慢、不稳定）"变为"AI 生成 Playwright 脚本 + 脚本自跑（快、可复现）"，同时让 develop prompt 强制前端代码加 `data-testid` 和 `window.__TEST__` 暴露状态。

**Architecture:** 四层改造：(1) develop prompt 新增可测试性约束，让生成的前端代码带 testid 和状态钩子；(2) test prompt 从"用 MCP 实时操作浏览器"改为"生成 .playwright/ 脚本 → 跑脚本 → 读报告"，且直接复用 deploy 阶段常驻的 Docker 容器；(3) phases.sh 的 test phase 新增 Playwright JSON 结果解析作为 shell 侧兜底；(4) Chrome DevTools MCP 仅用于调试失败场景。

**Tech Stack:** Bash (phantom shell) + Playwright Test (`@playwright/test`) + Chrome DevTools MCP（调试辅助）

---

### Task 1: develop prompt 新增前端可测试性约束

**Files:**
- Modify: `prompts/develop.md` — 前端设计规范章节

- [ ] **Step 1: 在 develop.md 的"前端设计规范"章节追加可测试性规则**

在 `prompts/develop.md` 的 `## 前端设计规范（如果项目有前端）` 章节末尾追加：

```markdown
### 前端可测试性（硬性）

所有可交互元素和关键状态容器**必须**带 `data-testid` 属性，命名规则：`<feature>-<element>-<action>`。例如：
- `data-testid="todo-input-create"` — 创建 todo 的输入框
- `data-testid="todo-list-container"` — todo 列表容器
- `data-testid="todo-item-delete"` — 删除按钮
- `data-testid="auth-form-login"` — 登录表单
- `data-testid="empty-state"` — 空态占位符
- `data-testid="loading-spinner"` — 加载态
- `data-testid="error-message"` — 错误提示

**aria-label** 也必须为所有非文字按钮（图标按钮）填写有意义的标签。

**全局测试钩子**：在应用入口暴露 `window.__TEST__` 对象，包含：
- `window.__TEST__.store` — 当前应用状态快照（如 Redux store / Zustand state）
- `window.__TEST__.user` — 当前登录用户信息（或 null）
- `window.__TEST__.ready` — 应用是否初始化完成（boolean）

生产构建可以通过环境变量 `VITE_ENABLE_TEST_HOOKS=true`（默认 true）控制是否暴露。
```

- [ ] **Step 2: 验证改动**

打开 `prompts/develop.md`，确认"前端可测试性"子章节在"前端设计规范"章节内，格式正确。

- [ ] **Step 3: Commit**

```bash
git add prompts/develop.md
git commit -m "feat(test): develop prompt 新增前端可测试性约束（data-testid + window.__TEST__）"
```

---

### Task 2: plan prompt 新增可测试性要求

**Files:**
- Modify: `prompts/plan.md` — 非功能需求章节

- [ ] **Step 1: 在 plan.md 的"非功能需求"推荐章节追加前端可测试性**

在 `prompts/plan.md` 的 `### 非功能需求` 列表末尾追加：

```markdown
- **前端可测试性**：所有可交互元素必须带 `data-testid`（命名：`<feature>-<element>-<action>`）；入口暴露 `window.__TEST__` 对象（含 store / user / ready 状态）
```

- [ ] **Step 2: Commit**

```bash
git add prompts/plan.md
git commit -m "feat(test): plan prompt 非功能需求新增前端可测试性要求"
```

---

### Task 3: 重写 test prompt — 从实时驱动改为脚本生成

**Files:**
- Modify: `prompts/test.md` — 几乎全部重写第四步 E2E 部分

- [ ] **Step 0: 重写 test.md 的"第一步：启动被测对象"为复用 deploy 容器**

将当前 test.md 的"第一步"从自己 docker build + run 改为直接复用 deploy 阶段常驻的容器：

```markdown
### 第一步：确认被测对象在线

Deploy phase 已经构建并启动了 Docker 容器（常驻运行）。你**不需要**自己 build 或 run。

```bash
PORT=$(cat .phantom/port)
CONTAINER="phantom-test-$(basename $(pwd))"

# 验证容器在跑
if docker ps --filter "name=^${CONTAINER}$" --filter "status=running" --format '{{.Names}}' | grep -q .; then
  echo "容器 $CONTAINER 在线，端口 $PORT"
else
  echo "容器 $CONTAINER 不在线，尝试本地启动"
  # 回退：本地跑
  PORT=$PORT <按项目技术栈跑 npm start / python main.py 等>
fi

# 验证端口可达
curl -sf http://localhost:$PORT/ > /dev/null || curl -sf http://localhost:$PORT/api/health > /dev/null
```

**如果容器不在线且本地也启动失败**：直接给这轮打一个低分（< 30），写清楚原因，不要继续。
```

- [ ] **Step 1: 重写 test.md 的"第四步：E2E 测试"**

将当前的"用 Playwright MCP 实时操作"替换为"生成 Playwright 脚本 + 执行"模式。新的第四步：

```markdown
### 第四步：E2E 测试（生成 Playwright 脚本，仅对有前端的项目）

**策略**：AI 生成可独立运行的 Playwright 测试脚本，由 shell 执行。不要用 MCP 实时驱动浏览器。

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

#### 4e. 用 Chrome DevTools MCP 调试失败（可选）

如果有测试失败且原因不明，可以用 chrome-devtools MCP 工具辅助调试：
- `navigate_page` 到失败页面
- `list_console_messages` 查看 console error
- `list_network_requests` 查看网络异常
- `take_screenshot` 截图留证
- `evaluate_script` 跑 JS 检查 `window.__TEST__` 状态

这是**调试手段**，不是测试手段。测试以脚本结果为准。
```

- [ ] **Step 2: 更新"硬约束"章节**

将：
```
- 前端项目必须用 Playwright MCP 点击（不是 curl）
```

改为：
```
- 前端项目必须生成 Playwright 脚本并执行（不是用 MCP 实时操作）
- 脚本必须用 data-testid 定位，禁止 CSS 选择器
- 可用 Chrome DevTools MCP 辅助调试失败场景
```

- [ ] **Step 3: 删除"第六步：清理"中的 docker 清理**

由于 deploy phase 现在容器常驻，test phase 不应该清理容器。将第六步改为：

```markdown
### 第六步：清理

如果是本地跑的开发服务器，杀掉对应进程。**不要清理 Docker 容器**（容器由 deploy phase 管理，常驻运行）。
```

- [ ] **Step 4: 验证 test.md 完整性**

完整读一遍 test.md，确认：
- 第一步到第六步结构完整
- 没有遗留的 `mcp__playwright__` 引用
- Chrome DevTools MCP 只用于调试，不用于主测试流程

- [ ] **Step 5: Commit**

```bash
git add prompts/test.md
git commit -m "feat(test): test prompt 从实时驱动改为脚本生成模式 + Chrome DevTools 调试"
```

---

### Task 4: 更新 phases.sh — shell 侧解析 Playwright JSON 结果作为兜底

**Files:**
- Modify: `lib/phases.sh` — `run_test_phase` 函数

当前 shell 只从 AI 写的 `test-report-iter<N>.md` 提取总分。新增：如果 `.playwright/results.json` 存在，shell 直接解析 Playwright 测试通过率作为辅助数据，log 出来供参考。AI 的 rubric 打分仍然是主判断依据，但 Playwright 结果可以作为 sanity check。

- [ ] **Step 1: 在 `run_test_phase` 中 AI 调用之后、提取分数之前，新增 Playwright 结果解析**

在 `run_test_phase` 的 `ai_run tester` 调用之后、`_extract_score_from_report` 之前，插入：

```bash
  # 辅助：解析 Playwright JSON 结果（如果 tester 生成了脚本并跑了）
  local pw_results="$work_dir/.playwright/results.json"
  if [[ -f "$pw_results" ]]; then
    local pw_total pw_passed pw_failed
    pw_total=$(python3 -c "
import json, sys
r = json.load(open('$pw_results'))
specs = r.get('suites', [])
total = passed = failed = 0
def count(suites):
    global total, passed, failed
    for s in suites:
        for t in s.get('specs', []):
            for test in t.get('tests', []):
                total += 1
                status = test.get('results', [{}])[-1].get('status', '')
                if status == 'passed': passed += 1
                elif status in ('failed', 'timedOut'): failed += 1
        count(s.get('suites', []))
count(specs)
print(f'{total} {passed} {failed}')
" 2>/dev/null || echo "0 0 0")
    read -r pw_total pw_passed pw_failed <<< "$pw_total"
    if [[ "$pw_total" -gt 0 ]]; then
      log_info "Playwright 结果：${pw_passed}/${pw_total} passed, ${pw_failed} failed"
    fi
  fi
```

这段只做日志输出，不影响 pass/fail 判断。

- [ ] **Step 2: 验证语法**

```bash
bash -n lib/phases.sh && echo "OK"
```

- [ ] **Step 3: Commit**

```bash
git add lib/phases.sh
git commit -m "feat(test): shell 侧解析 Playwright JSON 结果作为辅助日志"
```

---

### Task 5: 更新 CLAUDE.md 文档

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 在 Phase 函数第 5 条更新 test phase 描述**

将 CLAUDE.md 里的 test phase 描述从 "Playwright MCP" 改为反映新模式：

```
5. **`run_test_phase`** — 单次 test round。走 `ai_run tester`（跨模型），tester 生成 Playwright 测试脚本并执行 + curl 跑所有端点所有场景，按 rubric 打分写 `test-report-iter<N>.md`，shell 提取总分，≥80 pass，否则 fail 并写 return-packet。可用 Chrome DevTools MCP 辅助调试。
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 更新 CLAUDE.md test phase 描述（脚本生成模式）"
```

---

### Task 6: 合并推送

- [ ] **Step 1: 合并到 main 并推送**

```bash
git checkout main
git merge feat/harness-v2
git push origin main
git checkout feat/harness-v2
```
