import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  root: 'frontend',
  base: '/static/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'frontend/src'),
    },
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    assetsInlineLimit: 4096,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'frontend/index.html'),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'https://localhost:3000',
    },
  },
})
