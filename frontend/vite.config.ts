import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 後端跑 :8000;如果用同 origin 開發,可以加 proxy 避免 CORS:
    proxy: {
      '/auth': 'http://localhost:8000',
      '/sessions': 'http://localhost:8000',
      '/me': 'http://localhost:8000',
      '/uploads': 'http://localhost:8000',
      '/models': 'http://localhost:8000',
      '/healthz': 'http://localhost:8000',
      '/chat': {
        target: 'ws://localhost:8000',
        ws: true,
        // EPIPE / ECONNRESET 是 user 切對話 / reconnect 時的常態 — 吞掉
        // noisy stack trace,其它 error 照常 log 出來。
        configure: (proxy) => {
          proxy.on('error', (err: NodeJS.ErrnoException) => {
            if (
              err.code === 'EPIPE' ||
              err.code === 'ECONNRESET' ||
              err.code === 'ECONNABORTED'
            ) return
            // eslint-disable-next-line no-console
            console.error('[vite proxy /chat]', err)
          })
        },
      },
    },
  },
})
