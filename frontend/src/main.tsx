import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import { applyTheme, getThemePref, startSystemThemeWatcher } from './lib/theme'

// Apply persisted theme synchronously before React paints to avoid a flash
// of light theme when user has dark mode persisted.
applyTheme(getThemePref())

// Watch OS prefers-color-scheme so 'Follow system' actually keeps following
// even when SettingsPanel is unmounted.
startSystemThemeWatcher()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
