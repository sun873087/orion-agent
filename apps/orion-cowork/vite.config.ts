import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'

// Renderer 走 Vite dev server (:5174),Electron main 之後載這個 URL。
// W:`base: './'` 讓 production build 的 asset paths 用 relative,
// Electron loadFile(file://...) 才找得到 — 預設 `/` 在 file:// 變磁碟 root,
// `<script src="/assets/x.js">` 整個 404 → 白屏。
export default defineConfig({
  root: resolve(__dirname, 'renderer'),
  base: './',
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
  },
  build: {
    outDir: resolve(__dirname, 'dist/renderer'),
    emptyOutDir: true,
  },
})
