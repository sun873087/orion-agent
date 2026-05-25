import { useEffect, useState } from 'react'
import { useTranslation } from '../i18n'
import { speak, ttsAvailable } from '../lib/tts'

/** 朗讀 assistant 回應 — 只有 /voice/status 回 tts_available 才顯示。 */
export function ReadAloudButton({ text }: { text: string }) {
  const { t } = useTranslation()
  const [available, setAvailable] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    void ttsAvailable().then((a) => {
      if (alive) setAvailable(a)
    })
    return () => {
      alive = false
    }
  }, [])

  if (!available || !text.trim()) return null

  async function onClick() {
    setBusy(true)
    try {
      await speak(text)
    } catch {
      // 播放失敗(權限 / 網路)— 靜默,不擋閱讀
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      onClick={() => void onClick()}
      disabled={busy}
      title={t('chat.readAloud')}
      aria-label={t('chat.readAloud')}
      className="p-1 rounded-md text-claude-textFaint hover:text-claude-text hover:bg-claude-panel disabled:opacity-50 transition-colors"
    >
      <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
        <path
          d="M3 6v4h2.5L9 13V3L5.5 6H3z"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
        <path
          d="M11 6.5a2 2 0 010 3M12.5 5a4 4 0 010 6"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinecap="round"
        />
      </svg>
    </button>
  )
}
