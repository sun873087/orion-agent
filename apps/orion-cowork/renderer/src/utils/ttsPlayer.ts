/**
 * 全域 TTS 播放器(Phase 31-T)— 同時只允許一則訊息在念,切下一則自動 stop 舊的。
 *
 * 兩條 path:
 *   - 'web':window.speechSynthesis(瀏覽器內建,免費,使用系統聲音)
 *   - 'openai':呼 sidecar tts.synthesize → mp3 base64 → new Audio() 播
 *
 * UI 訂閱透過 subscribe(callback):任何 playing/stopped 變化 callback。
 * Component 用 useSyncExternalStore 包成 hook(避免重複實作)。
 */

import { synthesizeSpeech } from '../api/agent'

type Provider = 'web' | 'openai'
type Listener = () => void

/** 當前狀態。null = 沒在播。 */
let currentMessageId: string | null = null
let currentAudio: HTMLAudioElement | null = null
let currentUtterance: SpeechSynthesisUtterance | null = null
let currentObjectUrl: string | null = null
const listeners: Set<Listener> = new Set()

function emit() {
  for (const l of listeners) l()
}

export function subscribe(l: Listener): () => void {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

export function getPlayingMessageId(): string | null {
  return currentMessageId
}

export function isPlaying(messageId: string): boolean {
  return currentMessageId === messageId
}

/** 立即停止當前播放,清資源。任何 path 都 safe。 */
export function stop(): void {
  if (currentAudio) {
    try {
      currentAudio.pause()
      currentAudio.src = ''
    } catch {
      // ignore
    }
    currentAudio = null
  }
  if (currentObjectUrl) {
    try {
      URL.revokeObjectURL(currentObjectUrl)
    } catch {
      // ignore
    }
    currentObjectUrl = null
  }
  if (currentUtterance) {
    try {
      window.speechSynthesis.cancel()
    } catch {
      // ignore
    }
    currentUtterance = null
  }
  currentMessageId = null
  emit()
}

/** Strip markdown / code / 多餘換行,讓 TTS 念起來自然。 */
export function stripForTTS(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, '。(程式碼略過)')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/_([^_]+)_/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^[-*+]\s+/gm, '')
    .replace(/^\d+\.\s+/gm, '')
    .replace(/\n{2,}/g, '。\n')
    .trim()
}

/** Web Speech API path — 走系統 TTS,完全 client-side。 */
function playViaWebSpeech(messageId: string, text: string, speed: number, locale: string): void {
  if (typeof window === 'undefined' || !window.speechSynthesis) {
    console.warn('[TTS] Web Speech API not available')
    return
  }
  stop()
  const u = new SpeechSynthesisUtterance(text)
  // 對齊 i18n locale:zh-TW / zh-CN / en / ja → 對應系統 voice 語言
  u.lang = locale === 'zh-CN' ? 'zh-CN' : locale === 'ja' ? 'ja-JP' : locale === 'en' ? 'en-US' : 'zh-TW'
  u.rate = Math.max(0.1, Math.min(10, speed))
  u.onend = () => {
    if (currentUtterance === u) {
      currentUtterance = null
      currentMessageId = null
      emit()
    }
  }
  u.onerror = () => {
    if (currentUtterance === u) {
      currentUtterance = null
      currentMessageId = null
      emit()
    }
  }
  currentUtterance = u
  currentMessageId = messageId
  emit()
  window.speechSynthesis.speak(u)
}

/** OpenAI cloud path — 走 sidecar 拉 mp3 後播。延遲 ~1-2s 看網路。 */
async function playViaOpenAI(
  messageId: string,
  text: string,
  model: string,
  voice: string,
  speed: number,
): Promise<void> {
  stop()
  currentMessageId = messageId
  emit()
  try {
    const result = await synthesizeSpeech({
      text,
      provider: 'openai',
      model,
      voice,
      speed,
    })
    // 若 user 中途按了 stop 或切到別則,別蓋掉新狀態
    if (currentMessageId !== messageId) return
    if (result.cacheHit) {
      // 開發 / debug 提示用 — user 看不到也沒差,留 console 紀錄
      // eslint-disable-next-line no-console
      console.log(`[TTS] cache hit · ${result.charCount} chars · $0`)
    }
    const bytes = Uint8Array.from(atob(result.audioBase64), (c) => c.charCodeAt(0))
    const blob = new Blob([bytes], { type: result.mimeType })
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    audio.onended = () => {
      if (currentAudio === audio) {
        stop()
      }
    }
    audio.onerror = () => {
      if (currentAudio === audio) {
        stop()
      }
    }
    currentAudio = audio
    currentObjectUrl = url
    await audio.play()
  } catch (e) {
    console.warn('[TTS] OpenAI failed, falling back to Web Speech:', e)
    // Cloud fail 自動 fallback 到 Web Speech 不擾流程
    playViaWebSpeech(messageId, text, speed, 'zh-TW')
  }
}

/** Play 一則訊息;切下一則自動 stop 舊的。 */
export function play(
  messageId: string,
  text: string,
  opts: {
    provider: Provider
    model?: string
    voice?: string
    speed?: number
    locale?: string
  },
): void {
  const cleaned = stripForTTS(text)
  if (!cleaned) return
  const speed = opts.speed ?? 1.0
  if (opts.provider === 'web') {
    playViaWebSpeech(messageId, cleaned, speed, opts.locale ?? 'zh-TW')
  } else {
    void playViaOpenAI(messageId, cleaned, opts.model ?? 'tts-1', opts.voice ?? 'nova', speed)
  }
}
