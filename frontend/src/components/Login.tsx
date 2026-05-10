import { useState } from 'react'
import { apiFetch } from '../api/client'
import { setAuth } from '../api/auth'

interface Props {
  onLoggedIn: () => void
}

type Mode = 'login' | 'register'

export function Login({ onLoggedIn }: Props) {
  const [mode, setMode] = useState<Mode>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!username) {
      setError('username required')
      return
    }
    setError(null)
    setBusy(true)
    try {
      if (mode === 'register') {
        if (password.length < 8) {
          setError('password must be at least 8 characters')
          setBusy(false)
          return
        }
        await apiFetch('/auth/register', {
          method: 'POST',
          body: { username, password },
          authRequired: false,
        })
      }
      const resp = await apiFetch<{ token: string; user_id: string }>(
        '/auth/login',
        {
          method: 'POST',
          body: { username, password },
          authRequired: false,
        },
      )
      setAuth(resp.token, username)
      onLoggedIn()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-full flex items-center justify-center bg-claude-cream px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-claude-orange text-white text-lg font-semibold">
            O
          </span>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight">
            Welcome to Orion
          </h1>
          <p className="mt-1 text-sm text-claude-textDim">
            {mode === 'login' ? 'Sign in to continue' : 'Create an account'}
          </p>
        </div>

        <div className="bg-white dark:bg-claude-panel dark:ring-1 dark:ring-claude-border rounded-2xl shadow-soft dark:shadow-none p-6 space-y-3">
          <div className="flex p-1 bg-claude-panel dark:bg-claude-cream rounded-lg text-[13px]">
            <button
              className={`flex-1 py-1.5 rounded-md transition-colors ${
                mode === 'login'
                  ? 'bg-white dark:bg-claude-panel text-claude-text shadow-soft dark:shadow-none dark:ring-1 dark:ring-claude-border font-medium'
                  : 'text-claude-textDim hover:text-claude-text'
              }`}
              onClick={() => setMode('login')}
            >
              Sign in
            </button>
            <button
              className={`flex-1 py-1.5 rounded-md transition-colors ${
                mode === 'register'
                  ? 'bg-white dark:bg-claude-panel text-claude-text shadow-soft dark:shadow-none dark:ring-1 dark:ring-claude-border font-medium'
                  : 'text-claude-textDim hover:text-claude-text'
              }`}
              onClick={() => setMode('register')}
            >
              Create account
            </button>
          </div>

          <div className="space-y-2">
            <label className="text-[12px] font-medium text-claude-textDim block">
              Username
            </label>
            <input
              className="w-full border border-claude-border rounded-lg px-3 py-2 text-sm bg-white dark:bg-claude-cream text-claude-text focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <label className="text-[12px] font-medium text-claude-textDim block">
              Password
              {mode === 'register' && (
                <span className="ml-1 text-claude-textFaint">
                  (min 8 chars)
                </span>
              )}
            </label>
            <input
              className="w-full border border-claude-border rounded-lg px-3 py-2 text-sm bg-white dark:bg-claude-cream text-claude-text focus:outline-none focus:border-claude-orange focus:ring-2 focus:ring-claude-orange/20 transition-shadow"
              type="password"
              placeholder={mode === 'login' ? '(empty for dev mode)' : ''}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void submit()
              }}
            />
          </div>

          {error && (
            <div className="text-[13px] text-red-700 bg-red-50 border border-red-100 dark:text-red-300 dark:bg-red-950/40 dark:border-red-900/60 px-3 py-2 rounded-md">
              {error}
            </div>
          )}

          <button
            className="w-full bg-claude-orange hover:bg-claude-orangeHover disabled:bg-claude-border disabled:text-claude-textFaint disabled:cursor-not-allowed text-white rounded-lg py-2.5 text-sm font-medium transition-colors mt-2"
            onClick={() => void submit()}
            disabled={busy}
          >
            {busy ? '…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </div>

        <p className="mt-4 text-[12px] text-claude-textFaint text-center px-4">
          Dev mode (no <code className="font-mono">ORION_DB_URL</code>) accepts
          any username with empty password.
        </p>
      </div>
    </div>
  )
}
