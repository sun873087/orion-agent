const KEY_PROVIDER = 'orion.preferred_provider'
const KEY_MODEL = 'orion.preferred_model'

export interface ModelChoice {
  provider: string
  model: string
}

export function getPreferredModel(): ModelChoice | null {
  try {
    const provider = localStorage.getItem(KEY_PROVIDER)
    const model = localStorage.getItem(KEY_MODEL)
    if (!provider || !model) return null
    return { provider, model }
  } catch {
    return null
  }
}

export function setPreferredModel(choice: ModelChoice): void {
  try {
    localStorage.setItem(KEY_PROVIDER, choice.provider)
    localStorage.setItem(KEY_MODEL, choice.model)
  } catch {
    // localStorage 滿 / disabled — 忽略,下次 fallback 到 catalog default
  }
}

export function clearPreferredModel(): void {
  try {
    localStorage.removeItem(KEY_PROVIDER)
    localStorage.removeItem(KEY_MODEL)
  } catch {
    // ignore
  }
}
