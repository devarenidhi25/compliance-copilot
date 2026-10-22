import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Built files are served by FastAPI: index.html at "/" and bundles under "/assets".
// During development (`npm run dev`) API calls are proxied to the local backend.
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 1600 },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'] },
});
