import { defineConfig } from 'vitest/config'

// store / i18n 邏輯測試。jsdom 提供 localStorage(stores 初始化會讀)。
// 元件(presentational)暫不測 — 見 Phase 0 決策。
export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
})
