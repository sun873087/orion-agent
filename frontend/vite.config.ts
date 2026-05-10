import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
//
// 後端跑 :8000;為了避免 CORS 同 origin 走 vite proxy。
//
// HTTP 端 proxy 設定:
// - `agent: false`:**完全禁用 agent / connection pool**。vite/http-proxy
//   預設會 keep-alive 連到 backend 的 socket,backend 一抖(重啟、長 LLM
//   request 佔 worker、GC pause、macOS App Nap)pool 裡的 socket 變 stale,
//   proxy 不知道繼續往死連線丟 → 卡到底。`agent: false` 強制每個 request
//   開全新 socket,完全沒 stale pool。每 request 多 ~1ms TCP handshake,
//   dev 環境可接受。
// - `timeout` + `proxyTimeout`(8s):多一道保險。
const HTTP_TARGET = 'http://localhost:8000'
const httpProxy = {
  target: HTTP_TARGET,
  changeOrigin: true,
  agent: false as const,
  timeout: 8_000,
  proxyTimeout: 8_000,
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/auth': httpProxy,
      '/sessions': httpProxy,
      '/me': httpProxy,
      '/uploads': httpProxy,
      '/models': httpProxy,
      '/healthz': httpProxy,
      '/oauth': httpProxy,
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
            )
              return
            console.error('[vite proxy /chat]', err)
          })
        },
      },
    },
  },
})
