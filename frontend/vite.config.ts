/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // MP_VITE_PORT / MP_API_TARGET let parallel worktrees run side by side.
    port: Number(process.env.MP_VITE_PORT ?? 5199),
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.MP_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 900,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // tokens.test.ts reads the token file as raw text.
    css: { include: [/tokens\.css/] },
    restoreMocks: true,
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
