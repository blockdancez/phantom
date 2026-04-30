const { test, expect } = require('@playwright/test');

test.beforeEach(async ({ page }) => {
  page.on('console', msg => {
    if (msg.type() === 'error') console.log('[browser error]', msg.text());
  });
  page.on('pageerror', err => console.log('[page error]', err.message));
  page.on('response', response => {
    if (!response.ok() && !response.url().includes('_next')) {
      console.log('[network error]', response.status(), response.url());
    }
  });
});

test('Dashboard page loads correctly', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/AI Idea Finder/);
});

test('Dashboard shows key stats cards', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Total Sources')).toBeVisible();
  await expect(page.getByText('Analysis Reports')).toBeVisible();
  await expect(page.getByText('Latest Score')).toBeVisible();
});

test('Dashboard shows section headers', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Latest Ideas')).toBeVisible();
  await expect(page.getByText('Recent Sources')).toBeVisible();
});

test('Dashboard shows empty state messages when no data', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('No analysis results yet')).toBeVisible();
  await expect(page.getByText('No data collected yet')).toBeVisible();
});

test('Sidebar navigation is visible with correct links', async ({ page }) => {
  await page.goto('/');
  const sidebar = page.locator('aside');
  await expect(sidebar).toBeVisible();
  await expect(sidebar.getByText('Dashboard')).toBeVisible();
  await expect(sidebar.getByText('Data Sources')).toBeVisible();
  await expect(sidebar.getByText('Analysis')).toBeVisible();
});

test('Dashboard link is active on home page', async ({ page }) => {
  await page.goto('/');
  const dashboardLink = page.locator('aside a[href="/"]');
  await expect(dashboardLink).toBeVisible();
});
