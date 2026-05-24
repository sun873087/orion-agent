/**
 * 輕量 i18n — 無外部 dep。
 *
 * 用法:
 *   const { t } = useTranslation()
 *   t('sidebar.newChat')
 *   t('sidebar.msgCount', { n: 3 })
 *
 * 切語言走 useUiStore.setLocale(),locale 變更時整個 app re-render(zustand 訂閱)。
 */
import enMessages from './locales/en'
import jaMessages from './locales/ja'
import zhCNMessages from './locales/zh-CN'
import zhTWMessages from './locales/zh-TW'
import { type Locale } from './types'
import { useUiStore } from '../store/uiStore'

export { LOCALES, LOCALE_LABELS, detectDefaultLocale } from './types'
export type { Locale }

type Messages = Record<string, string>

const dictionaries: Record<Locale, Messages> = {
  'zh-TW': zhTWMessages,
  en: enMessages,
  'zh-CN': zhCNMessages,
  ja: jaMessages,
}

function format(
  template: string,
  params?: Record<string, string | number>,
): string {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (_, key) => {
    const v = params[key]
    return v === undefined ? `{${key}}` : String(v)
  })
}

/** 直接拿 message(non-hook,給 store / utility 用)。命中 fallback:locale → en → key。 */
export function tFor(
  locale: Locale,
  key: string,
  params?: Record<string, string | number>,
): string {
  const msg = dictionaries[locale]?.[key] ?? dictionaries.en[key] ?? key
  return format(msg, params)
}

/** React hook — 訂閱 locale,變更時整個元件 re-render。 */
export function useTranslation(): {
  t: (key: string, params?: Record<string, string | number>) => string
  locale: Locale
} {
  const locale = useUiStore((s) => s.locale)
  function t(key: string, params?: Record<string, string | number>): string {
    return tFor(locale, key, params)
  }
  return { t, locale }
}
