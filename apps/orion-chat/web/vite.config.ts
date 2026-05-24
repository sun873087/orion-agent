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
// 後端 target 預設 :8000(dev);Playwright 整合測試用 ORION_API_TARGET 指到
// mock-provider 的 ephemeral port,避免 clobber dev server。
const HTTP_TARGET = process.env.ORION_API_TARGET ?? 'http://localhost:8000'
const WS_TARGET = HTTP_TARGET.replace(/^http/, 'ws')
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
      '/skills': httpProxy,
      '/roles': httpProxy,
      '/projects': httpProxy,
      '/mcp': httpProxy,
      '/schedules': httpProxy,
      '/collaborations': httpProxy,
      '/uploads': httpProxy,
      '/models': httpProxy,
      '/healthz': httpProxy,
      '/oauth': httpProxy,
      '/chat': {
        target: WS_TARGET,
        ws: true,
        // EPIPE / ECONNRESET / writeAfterFIN 是 user 切對話 / reconnect 時的
        // 常態。Vite 內建會在 `proxy.on('error')` 用 config.logger 把這些
        // 印成 `[vite] ws proxy error:` — 而 configure 跑在 Vite 註冊
        // listener 之前,單純加 handler 蓋不掉 Vite 那條 log。
        // 改為攔截 proxy.emit,在 error 事件還沒派發前就吞掉已知 noise,
        // Vite 的 listener 根本不會被觸發。
        configure: (proxy) => {
          const SILENT_CODES = new Set([
            'EPIPE',
            'ECONNRESET',
            'ECONNABORTED',
            'ERR_STREAM_WRITE_AFTER_END',
          ])
          const originalEmit = proxy.emit.bind(proxy)
          proxy.emit = ((event: string, ...args: unknown[]) => {
            if (event === 'error') {
              const err = args[0] as NodeJS.ErrnoException | undefined
              if (err?.code && SILENT_CODES.has(err.code)) return false
            }
            return originalEmit(event, ...(args as [unknown]))
          }) as typeof proxy.emit
        },
      },
    },
  },
})
