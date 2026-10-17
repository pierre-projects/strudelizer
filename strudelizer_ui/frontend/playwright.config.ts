// The browser tests drive the real app against a real `strudelize ui` server,
// so they need the static files built first (`npm run build`) and a network
// connection, because Strudel fetches its samples from the web.
import { defineConfig, devices } from '@playwright/test';

const PORT = 8765;

export default defineConfig({
  testDir: './tests',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1280, height: 900 },
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `python -m strudelizer_ui --no-browser --port ${PORT}`,
    cwd: '../..',
    url: `http://127.0.0.1:${PORT}/api/plugins`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
