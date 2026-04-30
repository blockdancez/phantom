const fs = require('fs');
const { defineConfig } = require('@playwright/test');

const port = fs.existsSync('.phantom/port')
  ? fs.readFileSync('.phantom/port', 'utf8').trim()
  : '3000';

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 30000,
  use: {
    baseURL: `http://localhost:${port}`,
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
  },
  retries: 1,
});
