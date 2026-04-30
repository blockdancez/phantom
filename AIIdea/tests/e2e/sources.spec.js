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

test('Sources page loads correctly', async ({ page }) => {
  await page.goto('/sources');
  await expect(page.getByRole('heading', { name: /Data Sources/i })).toBeVisible();
});

test('Sources page shows description', async ({ page }) => {
  await page.goto('/sources');
  await expect(page.getByText(/collected trending data/i)).toBeVisible();
});

test('Sources page shows empty state when no items', async ({ page }) => {
  await page.goto('/sources');
  await expect(page.getByText(/No items collected yet/i)).toBeVisible();
});

test('Navigate from dashboard to sources page', async ({ page }) => {
  await page.goto('/');
  await page.locator('aside').getByText('Data Sources').click();
  await expect(page).toHaveURL(/\/sources/);
  await expect(page.getByRole('heading', { name: /Data Sources/i })).toBeVisible();
});
