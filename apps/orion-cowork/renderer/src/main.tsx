import React from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './index.css'

// First-render 套用 persisted theme,避免 hydrate 完成前閃一下錯誤主題。
// zustand store(store/settings.ts)會在之後接管。
try {
  const raw = localStorage.getItem('orion-cowork-settings/v1')
  const theme = raw ? JSON.parse(raw)?.state?.theme : 'dark'
  if (theme === 'light') {
    document.documentElement.classList.remove('dark')
  } else {
    document.documentElement.classList.add('dark')
  }
} catch {
  document.documentElement.classList.add('dark')
}

const root = document.getElementById('root')
if (!root) throw new Error('#root not found')
createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
