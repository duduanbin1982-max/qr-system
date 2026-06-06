import { defineConfig } from 'vite'
import { resolve } from 'path'

// 多页面入口：index-v2.html 为主入口，其他页面独立构建
export default defineConfig({
  root: 'public',
  base: '/',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'public/index-v2.html'),
        mobile: resolve(__dirname, 'public/mobile.html'),
        board: resolve(__dirname, 'public/board.html'),
        bigscreen: resolve(__dirname, 'public/bigscreen.html'),
        reports: resolve(__dirname, 'public/reports.html'),
      },
    },
    // 保留 CDN 加载的 Vue 等外部依赖
    // JS 文件小于 4KB 内联，减少请求数
    assetsInlineLimit: 4096,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'https://localhost:3000',
    },
  },
  // 保留 {$ $} 模板分隔符（Flask Jinja2 兼容）
  // Vite 默认不处理 .html 中的模板语法
})
