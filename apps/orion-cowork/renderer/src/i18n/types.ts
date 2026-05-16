/** i18n 的型別 + 純函式 — 不依賴 store,可被 store 安全 import。 */

export const LOCALES = ['zh-TW', 'en', 'zh-CN', 'ja'] as const
export type Locale = (typeof LOCALES)[number]

/** 從 navigator.language 推預設 locale,沒命中 fallback en。 */
export function detectDefaultLocale(): Locale {
  if (typeof navigator === 'undefined') return 'en'
  const lang = navigator.language
  if (lang.startsWith('zh')) {
    if (lang.toLowerCase().includes('tw') || lang.toLowerCase().includes('hk')) {
      return 'zh-TW'
    }
    return 'zh-CN'
  }
  if (lang.startsWith('ja')) return 'ja'
  return 'en'
}
