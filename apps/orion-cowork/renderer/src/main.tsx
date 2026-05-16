import React from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './index.css'

// 桌機 app 預設 dark mode(可後續加切換)
document.documentElement.classList.add('dark')

const root = document.getElementById('root')
if (!root) throw new Error('#root not found')
createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
