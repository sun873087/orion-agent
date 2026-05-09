import { clearAuth, getToken } from './auth'

export class ApiError extends Error {
  status: number
  body: unknown

  constructor(status: number, message: string, body: unknown = null) {
    super(message)
    this.status = status
    this.body = body
    this.name = 'ApiError'
  }
}

interface ApiOpts {
  method?: string
  body?: unknown
  signal?: AbortSignal
  authRequired?: boolean
}

/**
 * fetch wrapper:自動帶 Authorization header,401 → clearAuth + reload。
 *
 * 不做 base URL — Vite proxy 已把 /sessions/* 等代理到 backend。
 */
export async function apiFetch<T = unknown>(
  path: string,
  opts: ApiOpts = {},
): Promise<T> {
  const { method = 'GET', body, signal, authRequired = true } = opts

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  const token = getToken()
  if (authRequired && token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const init: RequestInit = { method, headers, signal }
  if (body !== undefined) {
    init.body = typeof body === 'string' ? body : JSON.stringify(body)
  }

  const r = await fetch(path, init)
  if (r.status === 401) {
    clearAuth()
    // 不 reload — 由 App / Login 自己重新導航
    throw new ApiError(401, 'unauthorized')
  }
  if (!r.ok) {
    let bodyJson: unknown = null
    try {
      bodyJson = await r.json()
    } catch {
      // 非 JSON 回應
    }
    const detail =
      bodyJson && typeof bodyJson === 'object' && 'detail' in bodyJson
        ? String((bodyJson as { detail: unknown }).detail)
        : `HTTP ${r.status}`
    throw new ApiError(r.status, detail, bodyJson)
  }
  if (r.status === 204) {
    return undefined as T
  }
  // 嘗試 JSON;空 body 回 undefined
  const text = await r.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

/** multipart upload(檔案上傳專用)。 */
export async function apiUpload<T = unknown>(
  path: string,
  formData: FormData,
): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  const r = await fetch(path, { method: 'POST', body: formData, headers })
  if (r.status === 401) {
    clearAuth()
    throw new ApiError(401, 'unauthorized')
  }
  if (!r.ok) {
    let bodyJson: unknown = null
    try {
      bodyJson = await r.json()
    } catch {
      /* ignore */
    }
    throw new ApiError(r.status, `upload failed: HTTP ${r.status}`, bodyJson)
  }
  return (await r.json()) as T
}
