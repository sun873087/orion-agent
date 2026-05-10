import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
//
// 後端跑 :8000;為了避免 CORS 同 origin 走 vite proxy。
//
// HTTP 端 proxy 統一加 `timeout` + `proxyTimeout`(8s):vite 的
// http-proxy-middleware 預設會 keep-alive backend 連線,backend 一抖
// (重啟、長 request 把 worker 佔住、甚至 GC pause)那條 socket 變 stale,
// proxy 無法察覺繼續往死連線丟 → request 卡到底。設 timeout 後 vite 主動
// 砍 idle 8s 以上的連線,client 端的 retry 才能立即接手。
const HTTP_TARGET = 'http://localhost:8000'
const httpProxy = {
  target: HTTP_TARGET,
  changeOrigin: true,
  timeout: 8_000,
  proxyTimeout: 8_000,
}

export default defineConfig({
  plugins: [react()],
  server: {
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
