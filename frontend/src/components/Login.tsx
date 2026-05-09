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
    <div className="min-h-full flex items-center justify-center bg-gray-50">
      <div className="bg-white p-8 rounded-lg shadow border border-gray-200 w-96 space-y-3">
        <h1 className="text-2xl font-bold mb-2">Orion Agent</h1>
        <div className="flex gap-2">
          <button
            className={`flex-1 py-1 text-sm rounded ${
              mode === 'login'
                ? 'bg-blue-100 text-blue-800 border border-blue-300'
                : 'bg-gray-100 hover:bg-gray-200'
            }`}
            onClick={() => setMode('login')}
          >
            Login
          </button>
          <button
            className={`flex-1 py-1 text-sm rounded ${
              mode === 'register'
                ? 'bg-blue-100 text-blue-800 border border-blue-300'
                : 'bg-gray-100 hover:bg-gray-200'
            }`}
            onClick={() => setMode('register')}
          >
            Register
          </button>
        </div>

        <input
          className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
          placeholder="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />
        <input
          className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
          placeholder={
            mode === 'register'
              ? 'password (min 8 chars)'
              : 'password (or empty for dev mode)'
          }
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void submit()
          }}
        />

        {error && (
          <div className="text-sm text-red-600 bg-red-50 p-2 rounded">
            {error}
          </div>
        )}

        <button
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white rounded py-2 text-sm font-semibold"
          onClick={() => void submit()}
          disabled={busy}
        >
          {busy ? '…' : mode === 'login' ? 'Login' : 'Register & Login'}
        </button>

        <p className="text-xs text-gray-500 pt-2">
          Dev mode (no <code>ORION_DB_URL</code>) accepts any username with empty password.
        </p>
      </div>
    </div>
  )
}
