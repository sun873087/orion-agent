import { useEffect, useState } from 'react'
import {
  Brain,
  Building2,
  Code2,
  Database,
  ExternalLink,
  FileText,
  Folder,
  Shield,
  Sparkles,
  User,
  Wrench,
} from 'lucide-react'

import { getPrefs } from '../../api/agent'
import { useTranslation } from '../../i18n'

/** Settings → 關於 — app 介紹、版本、資料儲存位置、技術棧、隱私聲明。 */
export function AboutSection() {
  const { t } = useTranslation()
  const [defaultWorkspace, setDefaultWorkspace] = useState<string>('')

  useEffect(() => {
    getPrefs()
      .then((p) => setDefaultWorkspace(p.default_workspace_dir ?? ''))
      .catch(() => {})
  }, [])

  const dataLocations = [
    {
      icon: <Database size={14} />,
      label: 'Session DB',
      path: '~/.orion-cowork/sessions.db',
      note: '對話歷史、metadata、attachments index(SQLite)',
    },
    {
      icon: <FileText size={14} />,
      label: '附件圖',
      path: '~/.orion-cowork/blobs/',
      note: '訊息附件 raw bytes(by content hash 去重)',
    },
    {
      icon: <Brain size={14} />,
      label: '記憶 / Skills',
      path: '~/.orion-cowork/users/cowork-local/{memory,skills}/',
      note: '個人對話用;Project chat 走 <workspace>/.orion-cowork/',
    },
    {
      icon: <Folder size={14} />,
      label: '預設工作資料夾',
      path: defaultWorkspace || '~/.orion-cowork/users/cowork-local/workspace/',
      note: '/export、AI 寫檔的預設目的地',
    },
    {
      icon: <Wrench size={14} />,
      label: 'MCP 伺服器設定',
      path: '~/.orion-cowork/mcp.json',
      note: 'App 級 MCP servers(project 可在 <ws>/.orion-cowork/mcp.json 加)',
    },
    {
      icon: <Sparkles size={14} />,
      label: 'API Keys / 偏好',
      path: 'localStorage(由 OS keychain 保管 API key)',
      note: '模型選擇、主題、locale、auto-compact 設定等',
    },
  ]

  const features = [
    { name: '多 provider', desc: 'Anthropic / OpenAI 切換,各自獨立 model picker' },
    { name: '對話 compact', desc: '到閾值自動摘要前段對話釋出 token / 手動 /compact' },
    { name: 'MCP 伺服器', desc: 'Plug-in 外部工具(檔案系統、瀏覽器、registry 等)' },
    { name: 'Skills', desc: '可上傳 SKILL.md 資料夾擴展 model 行為,bundled / system / user / project 四層' },
    { name: 'Projects', desc: '對話跟 workspace 資料夾綁定,co-located memory / skills / mcp' },
    { name: '記憶系統', desc: 'auto-extract 對話中的事實寫進 markdown,下次自動載入' },
    { name: 'STT 語音輸入', desc: 'OpenAI Whisper / Google STT,本地錄音 → 文字' },
    { name: 'Cache-friendly prompt', desc: '4 BP rolling cache,system / mode / messages 分層 cache 命中' },
  ]

  const stack = [
    { label: 'Electron', tag: 'desktop shell' },
    { label: 'React 19 + TypeScript', tag: 'renderer' },
    { label: 'TailwindCSS', tag: 'styling' },
    { label: 'Zustand', tag: 'state' },
    { label: 'Python 3.12 + asyncio', tag: 'sidecar' },
    { label: 'orion-sdk + orion-model', tag: 'core engine' },
    { label: 'SQLite (aiosqlite)', tag: 'session DB' },
  ]

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-accent/10 text-accent">
          <Sparkles size={32} strokeWidth={1.5} />
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex items-baseline gap-2">
            <h2 className="text-2xl font-semibold tracking-tight text-fg-base">
              Orion Cowork
            </h2>
            <span className="font-mono text-xs text-fg-subtle">v0.1.0 · Phase 31</span>
          </div>
          <p className="text-sm text-fg-muted">
            桌面端 AI 助手 — 對話、工具、技能、MCP 整合都在本機跑,你的資料不離開電腦。
          </p>
        </div>
      </div>

      {/* Features */}
      <Section icon={<Sparkles size={14} />} title="主要功能">
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {features.map((f) => (
            <li
              key={f.name}
              className="rounded-lg border border-bg-hover bg-bg-panel px-3 py-2"
            >
              <div className="text-sm font-medium text-fg-base">{f.name}</div>
              <div className="text-xs text-fg-muted">{f.desc}</div>
            </li>
          ))}
        </ul>
      </Section>

      {/* Data locations */}
      <Section icon={<Folder size={14} />} title="資料儲存位置">
        <ul className="flex flex-col gap-2">
          {dataLocations.map((d) => (
            <li
              key={d.label}
              className="flex items-start gap-3 rounded-lg border border-bg-hover bg-bg-panel px-3 py-2"
            >
              <div className="mt-0.5 shrink-0 text-fg-muted">{d.icon}</div>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-medium text-fg-base">{d.label}</span>
                </div>
                <div className="mt-0.5 truncate font-mono text-[11px] text-fg-muted">
                  {d.path}
                </div>
                <div className="mt-0.5 text-[11px] text-fg-subtle">{d.note}</div>
              </div>
            </li>
          ))}
        </ul>
      </Section>

      {/* Tech stack */}
      <Section icon={<Code2 size={14} />} title="技術棧">
        <div className="flex flex-wrap gap-1.5">
          {stack.map((s) => (
            <span
              key={s.label}
              className="flex items-center gap-1.5 rounded-full border border-bg-hover bg-bg-panel px-2.5 py-1 text-xs text-fg-base"
              title={s.tag}
            >
              <span>{s.label}</span>
              <span className="text-[10px] text-fg-subtle">{s.tag}</span>
            </span>
          ))}
        </div>
      </Section>

      {/* Credits */}
      <Section icon={<User size={14} />} title="作者">
        <div className="flex flex-col gap-2 rounded-lg border border-bg-hover bg-bg-panel px-3 py-2.5">
          <div className="flex items-center gap-2 text-sm text-fg-base">
            <User size={14} className="text-fg-muted" />
            <span className="font-medium">鄭元森</span>
            <span className="font-mono text-xs text-fg-muted">(sam.cheng)</span>
          </div>
          <div className="flex items-center gap-2 text-xs text-fg-muted">
            <Building2 size={12} />
            <span>啓碁科技</span>
            <span className="text-fg-subtle">·</span>
            <span className="font-mono">WNC Corporation</span>
          </div>
        </div>
      </Section>

      {/* Privacy note */}
      <Section icon={<Shield size={14} />} title="隱私">
        <div className="rounded-lg border border-bg-hover bg-bg-panel px-3 py-2.5 text-xs leading-relaxed text-fg-muted">
          所有對話、附件、記憶、技能都存在本機 <code className="rounded bg-bg-hover px-1 font-mono">~/.orion-cowork/</code> 之下,
          不會上傳任何雲端服務。LLM 呼叫直接從 sidecar 連你設定的 provider
          (Anthropic / OpenAI 等),app 本身沒任何 telemetry / analytics / phone-home。
          API key 由 OS keychain(macOS Keychain / Windows Credential Manager / libsecret)保管,
          不會以明文存到 disk。
        </div>
      </Section>

      {/* Footer link */}
      <div className="flex items-center gap-1 text-[11px] text-fg-subtle">
        <button
          type="button"
          onClick={() =>
            window.shellApi.openPath('https://github.com/anthropics/claude-code')
          }
          className="flex items-center gap-1 hover:text-fg-muted"
          title="開啟 GitHub repo"
        >
          <span>本專案以 Claude Code SDK 為核心引擎</span>
          <ExternalLink size={10} />
        </button>
      </div>

      {/* Hidden — keep i18n key compatibility for older builds */}
      <span className="hidden">{t('settings.about.text')}</span>
    </div>
  )
}

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 text-sm font-medium text-fg-muted">
        {icon}
        <span>{title}</span>
      </h3>
      {children}
    </div>
  )
}
