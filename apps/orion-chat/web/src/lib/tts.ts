import { apiFetch } from '../api/client'

/**
 * TTS 朗讀 — POST /voice/tts 拿 base64 audio → Blob → HTMLAudioElement 播放。
 * voice status 模組層 cache(全頁共用,不每顆 bubble 打一次)。
 */

let statusCache: Promise<boolean> | null = null

export function ttsAvailable(): Promise<boolean> {
  if (statusCache === null) {
    statusCache = apiFetch<{ tts_available: boolean }>('/voice/status')
      .then((r) => r.tts_available)
      .catch(() => false)
  }
  return statusCache
}

export function resetTtsStatusCache(): void {
  statusCache = null
}

let current: HTMLAudioElement | null = null

export function stopSpeaking(): void {
  if (current) {
    current.pause()
    current = null
  }
}

export async function speak(text: string): Promise<void> {
  const res = await apiFetch<{ audio_base64: string; mime_type: string }>(
    '/voice/tts',
    { method: 'POST', body: { text } },
  )
  const bytes = Uint8Array.from(atob(res.audio_base64), (c) => c.charCodeAt(0))
  const blob = new Blob([bytes], { type: res.mime_type })
  const url = URL.createObjectURL(blob)
  stopSpeaking()
  const audio = new Audio(url)
  current = audio
  audio.onended = () => {
    URL.revokeObjectURL(url)
    if (current === audio) current = null
  }
  await audio.play()
}
