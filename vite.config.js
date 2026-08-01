import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const frontendRoot = resolve(__dirname, 'frontend')
const staticOutputDir = resolve(__dirname, 'public/static')
const packageManifest = JSON.parse(
  readFileSync(resolve(__dirname, 'package.json'), 'utf-8')
)
const applicationVersion = packageManifest.version

const applicationVersionPlugin = {
  name: 'application-version',
  transformIndexHtml(html) {
    return html.replaceAll('%APP_VERSION%', applicationVersion)
  },
}

export default defineConfig({
  root: frontendRoot,
  base: '/static/',
  plugins: [vue(), applicationVersionPlugin],
  define: {
    __APP_VERSION__: JSON.stringify(applicationVersion),
  },
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
