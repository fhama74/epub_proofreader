import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests', fullyParallel: false, workers: 1,
  use: {baseURL: 'http://127.0.0.1:8000', viewport: {width: 1440, height: 960}},
  webServer: process.env.EPROOF_EXTERNAL_SERVER ? undefined : {
    command: 'uv run uvicorn epub_proofreader.app:app --app-dir backend --host 127.0.0.1 --port 8000',
    cwd: '..', url: 'http://127.0.0.1:8000/api/health', reuseExistingServer: !process.env.CI,
  },
});
