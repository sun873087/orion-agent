/** i18n 的型別 + 純函式 — 不依賴 store,可被 store 安全 import。 */

export const LOCALES = ['zh-TW', 'en', 'zh-CN', 'ja'] as const
export type Locale = (typeof LOCALES)[number]

/** 語言選單顯示用的原生名稱(各自用自己的書寫系統,不翻譯)。 */
export const LOCALE_LABELS: Record<Locale, string> = {
  'zh-TW': '繁體中文',
  'zh-CN': '简体中文',
  en: 'English',
  ja: '日本語',
}

export function isLocale(v: unknown): v is Locale {
  return typeof v === 'string' && (LOCALES as readonly string[]).includes(v)
}

/** 從 navigator.language 推預設 locale,沒命中 fallback en。 */
export function detectDefaultLocale(): Locale {
  if (typeof navigator === 'undefined') return 'en'
  const lang = navigator.language
  if (lang.startsWith('zh')) {
    const lower = lang.toLowerCase()
    if (lower.includes('tw') || lower.includes('hk')) return 'zh-TW'
    return 'zh-CN'
  }
  if (lang.startsWith('ja')) return 'ja'
  return 'en'
}
