import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

const frontendRoot = resolve(__dirname, 'frontend')
const staticOutputDir = resolve(__dirname, 'public/static')

export default defineConfig({
  root: frontendRoot,
  base: '/static/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(frontendRoot, 'src'),
    },
  },
  build: {
    outDir: staticOutputDir,
    emptyOutDir: true,
    assetsInlineLimit: 4096,
    rollupOptions: {
      input: {
        main: resolve(frontendRoot, 'index.html'),
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
