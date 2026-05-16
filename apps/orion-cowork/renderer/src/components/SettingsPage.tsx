/**
 * 全頁 Settings — 左 categories,右 content。
 *
 * 加 section 只多一筆 SECTIONS:
 *   { id, label, group?, render }
 * group 為 optional;同 group 的 items 排在一起,group label 顯在上方。
 *
 * 切換 section / 開關 page 都走 store(useSettingsStore),Sidebar 的 popup
 * 也可以 openSettings('language') 直接跳到 Language section。
 */
import type { ComponentType } from 'react'
import { ArrowLeft, Brain, Folder, Info, type LucideIcon, Plug, Settings as SettingsIcon, ShieldCheck, Sparkles, Sun } from 'lucide-react'

import { useTranslation } from '../i18n'
import { useSettingsStore } from '../store/settings'

import { AboutSection } from './settings/AboutSection'
import { AppearanceSection } from './settings/AppearanceSection'
import { GeneralSection } from './settings/GeneralSection'
import { McpSection } from './settings/McpSection'
import { MemorySection } from './settings/MemorySection'
import { ModelsSection } from './settings/ModelsSection'
import { PermissionsSection } from './settings/PermissionsSection'
import { SkillsSection } from './settings/SkillsSection'

type SectionDef = {
  id: string
  /** i18n key for label。 */
  labelKey: string
  /** 同 group 排一起,group label 顯在 sidebar 上方;null/undefined 就放最頂層。 */
  groupKey?: string
  icon: LucideIcon
  render: ComponentType
}

// 新增 section 只在這多一筆 — page layout、切換邏輯都自動處理。
const SECTIONS: SectionDef[] = [
  {
    id: 'general',
    labelKey: 'settings.section.general',
    groupKey: 'settings.group.general',
    icon: Folder,
    render: GeneralSection,
  },
  {
    id: 'appearance',
    labelKey: 'settings.section.appearance',
    groupKey: 'settings.group.general',
    icon: Sun,
    render: AppearanceSection,
  },
  // 語言不放這 — 走 Sidebar popup 的 Language submenu(快捷且不重複)
  {
    id: 'models',
    labelKey: 'settings.section.model',
    groupKey: 'settings.group.desktop',
    icon: SettingsIcon,
    render: ModelsSection,
  },
  {
    id: 'memory',
    labelKey: 'settings.section.memory',
    groupKey: 'settings.group.desktop',
    icon: Brain,
    render: MemorySection,
  },
  {
    id: 'skills',
    labelKey: 'settings.section.skills',
    groupKey: 'settings.group.desktop',
    icon: Sparkles,
    render: SkillsSection,
  },
  {
    id: 'mcp',
    labelKey: 'settings.section.mcp',
    groupKey: 'settings.group.desktop',
    icon: Plug,
    render: McpSection,
  },
  {
    id: 'permissions',
    labelKey: 'settings.section.permissions',
    groupKey: 'settings.group.desktop',
    icon: ShieldCheck,
    render: PermissionsSection,
  },
  {
    id: 'about',
    labelKey: 'settings.section.about',
    groupKey: 'settings.group.desktop',
    icon: Info,
    render: AboutSection,
  },
]

function isMacUA(): boolean {
  return typeof navigator !== 'undefined' && /Mac|iPhone|iPod|iPad/.test(navigator.platform)
}

export function SettingsPage() {
  const { t } = useTranslation()
  const closeSettings = useSettingsStore((s) => s.closeSettings)
  const activeId = useSettingsStore((s) => s.activeSettingsSection)
  const setActive = useSettingsStore((s) => s.setActiveSettingsSection)

  const active = SECTIONS.find((s) => s.id === activeId) ?? SECTIONS[0]
  const ActiveRender = active.render

  // 用 reduce 把 sections 依 group 分組,維持原 array 順序
  const groups = groupSections(SECTIONS)

  return (
    <div className="flex h-full w-full flex-col bg-bg-base">
      {/* Top bar:← 返回 + Settings 標題 */}
      <header
        className={`app-drag flex h-12 shrink-0 items-center gap-3 border-b border-bg-hover ${
          isMacUA() ? 'pl-20 pr-4' : 'px-4'
        }`}
      >
        <button
          type="button"
          onClick={closeSettings}
          title={t('settings.back')}
          className="app-no-drag rounded p-1.5 text-fg-muted hover:bg-bg-hover hover:text-fg-base"
        >
          <ArrowLeft size={16} />
        </button>
        <h1 className="app-no-drag text-sm font-semibold">{t('settings.title')}</h1>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Left: category list */}
        <aside className="scrollbar-thin w-64 shrink-0 overflow-y-auto border-r border-bg-hover bg-bg-panel py-4">
          {groups.map((g, gi) => (
            <div key={g.key ?? `__top-${gi}`} className="mb-2 px-3">
              {g.key && (
                <div className="mb-1 px-2 text-xs font-medium uppercase tracking-wide text-fg-subtle">
                  {t(g.key)}
                </div>
              )}
              <ul className="flex flex-col gap-0.5">
                {g.items.map((s) => {
                  const Icon = s.icon
                  const isActive = s.id === active.id
                  return (
                    <li key={s.id}>
                      <button
                        type="button"
                        onClick={() => setActive(s.id)}
                        className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors ${
                          isActive
                            ? 'bg-bg-hover text-fg-base'
                            : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'
                        }`}
                      >
                        <Icon size={14} />
                        <span>{t(s.labelKey)}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </aside>

        {/* Right: active section content */}
        <main className="scrollbar-thin flex-1 overflow-y-auto px-8 py-6">
          <div className="mx-auto max-w-3xl">
            <h2 className="mb-4 text-lg font-semibold">{t(active.labelKey)}</h2>
            <ActiveRender />
          </div>
        </main>
      </div>
    </div>
  )
}

function groupSections(sections: SectionDef[]): Array<{ key: string | undefined; items: SectionDef[] }> {
  const out: Array<{ key: string | undefined; items: SectionDef[] }> = []
  for (const s of sections) {
    const last = out[out.length - 1]
    if (last && last.key === s.groupKey) {
      last.items.push(s)
    } else {
      out.push({ key: s.groupKey, items: [s] })
    }
  }
  return out
}
