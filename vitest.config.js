import { resolve } from 'path'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'


export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'frontend/src'),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['frontend/tests/unit/**/*.spec.js'],
    setupFiles: [resolve(__dirname, 'frontend/tests/setup.js')],
    clearMocks: true,
    restoreMocks: true,
    coverage: {
      provider: 'v8',
      reportsDirectory: resolve(__dirname, 'coverage/frontend'),
      reporter: ['text', 'json-summary', 'html'],
      include: ['frontend/src/**/*.{js,vue}'],
      exclude: ['frontend/src/lib/permissionFallback.generated.js'],
    },
  },
})
