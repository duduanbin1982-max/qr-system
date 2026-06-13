import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  base: '/static/',
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: '../public/static',
    emptyOutDir: true,
    rollupOptions: {
      external: ['chart.js'],
      output: {
        globals: { 'chart.js': 'Chart' },
        manualChunks: undefined,
      },
    },
  },
  server: {
    proxy: {
      '/api': 'https://localhost:3000',
    },
  },
})
