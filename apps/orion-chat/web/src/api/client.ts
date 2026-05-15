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
  /** Per-request timeout in ms. Defaults to DEFAULT_TIMEOUT_MS. Pass 0 to disable. */
  timeoutMs?: number
  /**
   * Number of automatic retries on transient failure (timeout / network /
   * 502 / 503 / 504). Defaults to 1 for idempotent methods (GET, HEAD),
   * 0 otherwise — POST/PUT/DELETE could have side effects so we don't
   * retry by default. Pass explicit `retries: 1` to opt-in for non-GET.
   */
  retries?: number
}

const DEFAULT_TIMEOUT_MS = 15_000
const RETRY_BACKOFF_MS = 300
const IDEMPOTENT_METHODS = new Set(['GET', 'HEAD'])
const RETRYABLE_STATUSES = new Set([502, 503, 504])

function withTimeout(
  external: AbortSignal | undefined,
  timeoutMs: number,
): { signal: AbortSignal; cleanup: () => void; timedOut: () => boolean } {
  const ctrl = new AbortController()
  let timedOutFlag = false
  const onExternal = () => ctrl.abort(external?.reason)
  if (external) {
    if (external.aborted) ctrl.abort(external.reason)
    else external.addEventListener('abort', onExternal, { once: true })
  }
  const t =
    timeoutMs > 0
      ? setTimeout(() => {
          timedOutFlag = true
          ctrl.abort(new DOMException('timeout', 'TimeoutError'))
        }, timeoutMs)
      : null
  return {
    signal: ctrl.signal,
    cleanup: () => {
      if (t !== null) clearTimeout(t)
      external?.removeEventListener('abort', onExternal)
    },
    timedOut: () => timedOutFlag,
  }
}

/**
 * fetch wrapper:自動帶 Authorization header,401 → clearAuth + reload。
 *
 * 不做 base URL — Vite proxy 已把 /sessions/* 等代理到 backend。
 *
 * Resilience:
 * - timeout (default 15s) via AbortController — hung request 不會卡無限轉圈
 * - idempotent methods (GET/HEAD) 自動 retry 一次,300ms backoff,涵蓋
 *   transient timeout / network error / 502 / 503 / 504。Vite dev proxy
 *   stale connection 抖一下就過、後端 cold start 也救得回來。
 * - 401 / 4xx 業務錯誤不 retry。POST/PUT/DELETE 預設不 retry (避免重送
 *   副作用),caller 可以顯式傳 `retries: 1`。
 */
export async function apiFetch<T = unknown>(
  path: string,
  opts: ApiOpts = {},
): Promise<T> {
  const {
    method = 'GET',
    body,
    signal,
    authRequired = true,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    retries = IDEMPOTENT_METHODS.has(method.toUpperCase()) ? 1 : 0,
  } = opts

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  const token = getToken()
  if (authRequired && token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const serializedBody =
    body === undefined
      ? undefined
      : typeof body === 'string'
        ? body
        : JSON.stringify(body)

  const attempt = async (): Promise<
    | {
        ok: true
        value: T
      }
    | { ok: false; transient: boolean; err: unknown }
  > => {
    // 外部 signal 已 abort → 立即停,不重試
    if (signal?.aborted) {
      return { ok: false, transient: false, err: signal.reason }
    }
    const t = withTimeout(signal, timeoutMs)
    const init: RequestInit = { method, headers, signal: t.signal }
    if (serializedBody !== undefined) init.body = serializedBody

    let r: Response
    try {
      r = await fetch(path, init)
    } catch (e) {
      t.cleanup()
      if (signal?.aborted) {
        return { ok: false, transient: false, err: signal.reason }
      }
      if (t.timedOut()) {
        return {
          ok: false,
          transient: true,
          err: new ApiError(0, `request timed out after ${timeoutMs}ms`, null),
        }
      }
      // network error (TypeError "Failed to fetch") — transient
      return { ok: false, transient: true, err: e }
    }
    t.cleanup()

    if (r.status === 401) {
      clearAuth()
      return {
        ok: false,
        transient: false,
        err: new ApiError(401, 'unauthorized'),
      }
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
      return {
        ok: false,
        transient: RETRYABLE_STATUSES.has(r.status),
        err: new ApiError(r.status, detail, bodyJson),
      }
    }
    if (r.status === 204) return { ok: true, value: undefined as T }
    const text = await r.text()
    if (!text) return { ok: true, value: undefined as T }
    return { ok: true, value: JSON.parse(text) as T }
  }

  let lastErr: unknown
  for (let i = 0; i <= retries; i++) {
    const res = await attempt()
    if (res.ok) return res.value
    lastErr = res.err
    if (!res.transient || i === retries) break
    await new Promise((r) => setTimeout(r, RETRY_BACKOFF_MS))
  }
  throw lastErr
}

const UPLOAD_TIMEOUT_MS = 120_000

/** multipart upload(檔案上傳專用)。 */
export async function apiUpload<T = unknown>(
  path: string,
  formData: FormData,
  opts: { signal?: AbortSignal; timeoutMs?: number } = {},
): Promise<T> {
  const { signal, timeoutMs = UPLOAD_TIMEOUT_MS } = opts
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  const t = withTimeout(signal, timeoutMs)
  let r: Response
  try {
    r = await fetch(path, {
      method: 'POST',
      body: formData,
      headers,
      signal: t.signal,
    })
  } catch (e) {
    t.cleanup()
    if (t.timedOut()) {
      throw new ApiError(0, `upload timed out after ${timeoutMs}ms`, null)
    }
    throw e
  }
  t.cleanup()
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
