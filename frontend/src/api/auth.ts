// JWT token 管理 — localStorage 簡單版。
// 過期 / 401 由 client.ts 偵測並 clearToken。

const TOKEN_KEY = 'orion.jwt'
const USER_KEY = 'orion.username'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getUsername(): string | null {
  return localStorage.getItem(USER_KEY)
}

export function setAuth(token: string, username: string): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, username)
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function isLoggedIn(): boolean {
  return !!getToken()
}
