import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'

// Phase E:Renderer 走 Vite dev server (:5174),Electron main 之後載這個 URL。
export default defineConfig({
  root: resolve(__dirname, 'renderer'),
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
