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

test('Analysis page loads correctly', async ({ page }) => {
  await page.goto('/analysis');
  await expect(page.getByRole('heading', { name: /Analysis Results/i })).toBeVisible();
});

test('Analysis page shows description', async ({ page }) => {
  await page.goto('/analysis');
  await expect(page.getByText(/AI-generated product ideas/i)).toBeVisible();
});

test('Analysis page shows empty state when no results', async ({ page }) => {
  await page.goto('/analysis');
  await expect(page.getByText(/No analysis results yet/i)).toBeVisible();
});

test('Navigate from dashboard to analysis page', async ({ page }) => {
  await page.goto('/');
  await page.locator('aside').getByText('Analysis').click();
  await expect(page).toHaveURL(/\/analysis/);
  await expect(page.getByRole('heading', { name: /Analysis Results/i })).toBeVisible();
});

test('Navigate between all pages', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();

  await page.locator('aside').getByText('Data Sources').click();
  await expect(page).toHaveURL(/\/sources/);

  await page.locator('aside').getByText('Analysis').click();
  await expect(page).toHaveURL(/\/analysis/);

  await page.locator('aside').getByText('Dashboard').click();
  await expect(page).toHaveURL('/');
});
