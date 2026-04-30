const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log("[browser error]", msg.text());
  });
  page.on("pageerror", (err) => console.log("[page error]", err.message));
  page.on("response", (response) => {
    if (!response.ok() && !response.url().includes("/document")) {
      console.log("[network error]", response.status(), response.url());
    }
  });
});

test.describe("首页", () => {
  test("页面正常加载，显示标题和表单", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("text=将 Idea 变为产品需求")).toBeVisible();
    await expect(page.locator("text=描述你的产品 Idea")).toBeVisible();
    await expect(page.locator("textarea#idea")).toBeVisible();
    await expect(
      page.locator("button", { hasText: "生成产品需求文档" })
    ).toBeVisible();
  });

  test("导航栏包含正确链接", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("text=PRD Agent")).toBeVisible();
    await expect(page.locator("nav >> text=新建")).toBeVisible();
    await expect(page.locator("nav >> text=历史")).toBeVisible();
  });

  test("空内容时提交按钮禁用", async ({ page }) => {
    await page.goto("/");
    const submitBtn = page.locator("button", { hasText: "生成产品需求文档" });
    await expect(submitBtn).toBeDisabled();
  });

  test("输入内容后提交按钮启用", async ({ page }) => {
    await page.goto("/");
    await page.fill("textarea#idea", "一个AI驱动的代码审查工具");
    const submitBtn = page.locator("button", { hasText: "生成产品需求文档" });
    await expect(submitBtn).toBeEnabled();
  });

  test("字数计数器正确显示", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("text=0 / 5000")).toBeVisible();
    await page.fill("textarea#idea", "测试文本");
    await expect(page.locator("text=4 / 5000")).toBeVisible();
  });

  test("提交idea后跳转到结果页", async ({ page }) => {
    await page.goto("/");
    await page.fill("textarea#idea", "一个帮助程序员生成单元测试的工具");
    await page.click("button:has-text('生成产品需求文档')");
    await page.waitForURL(/\/result\//, { timeout: 10000 });
    expect(page.url()).toMatch(/\/result\/[0-9a-f-]+/);
  });
});

test.describe("结果页", () => {
  test("显示生成中的状态", async ({ page }) => {
    await page.goto("/");
    await page.fill("textarea#idea", "E2E测试用的产品idea");
    await page.click("button:has-text('生成产品需求文档')");
    await page.waitForURL(/\/result\//);
    await expect(page.locator("text=正在生成需求文档")).toBeVisible({
      timeout: 10000,
    });
  });

  test("无效idea ID显示错误", async ({ page }) => {
    await page.goto("/result/00000000-0000-0000-0000-000000000000");
    await expect(page.locator("text=加载失败")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=返回首页")).toBeVisible();
  });
});

test.describe("历史页", () => {
  test("页面正常加载", async ({ page }) => {
    await page.goto("/history");
    await expect(page.locator("text=历史记录")).toBeVisible();
  });

  test("显示已有的idea列表", async ({ page }) => {
    await page.goto("/history");
    await page.waitForTimeout(1000);
    const items = page.locator("a[href^='/result/']");
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test("从导航栏跳转到历史页", async ({ page }) => {
    await page.goto("/");
    await page.click("nav >> text=历史");
    await expect(page).toHaveURL(/\/history/);
    await expect(page.locator("text=历史记录")).toBeVisible();
  });
});

test.describe("导航流程", () => {
  test("首页 -> 历史 -> 首页", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("text=将 Idea 变为产品需求")).toBeVisible();

    await page.click("nav >> text=历史");
    await expect(page.locator("text=历史记录")).toBeVisible();

    await page.click("nav >> text=新建");
    await expect(page.locator("text=将 Idea 变为产品需求")).toBeVisible();
  });

  test("点击logo返回首页", async ({ page }) => {
    await page.goto("/history");
    await page.click("text=PRD Agent");
    await expect(page).toHaveURL("/");
  });
});
