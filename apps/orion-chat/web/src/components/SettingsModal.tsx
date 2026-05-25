import { useEffect, useState } from 'react'
import { useTranslation } from '../i18n'
import { useUiStore } from '../store/uiStore'
import { ConnectionsPanel } from './ConnectionsPanel'
import { McpServersPanel } from './McpServersPanel'
import { MemoryPanel } from './MemoryPanel'
import { ModelSettingsPanel } from './ModelSettingsPanel'
import { ProjectsPanel } from './ProjectsPanel'
import { RolesPanel } from './RolesPanel'
import { SchedulesPanel } from './SchedulesPanel'
import { SettingsPanel } from './SettingsPanel'
import { SkillsPanel } from './SkillsPanel'
import { SoulPanel } from './SoulPanel'

type Tab =
  | 'general'
  | 'models'
  | 'memory'
  | 'skills'
  | 'roles'
  | 'soul'
  | 'projects'
  | 'schedules'
  | 'connections'

interface Props {
  onClose: () => void
}

const TABS: { key: Tab; labelKey: string; icon: JSX.Element }[] = [
  {
    key: 'general',
    labelKey: 'settings.tab.general',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.5" />
        <path
          d="M8 1.5v2M8 12.5v2M14.5 8h-2M3.5 8h-2"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    key: 'models',
    labelKey: 'settings.tab.models',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <rect
          x="3.5"
          y="3.5"
          width="9"
          height="9"
          rx="1.5"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        <path
          d="M6 1.5v2M10 1.5v2M6 12.5v2M10 12.5v2M12.5 6h2M12.5 10h2M1.5 6h2M1.5 10h2"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    key: 'memory',
    labelKey: 'settings.tab.memory',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <path
          d="M3 4a1 1 0 011-1h8a1 1 0 011 1v8a1 1 0 01-1 1H4a1 1 0 01-1-1V4z"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        <path
          d="M5.5 6.5h5M5.5 9h3"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    key: 'skills',
    labelKey: 'settings.tab.skills',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <path
          d="M8 1.5l1.8 3.7 4 .6-2.9 2.8.7 4L8 10.7 4.4 12.6l.7-4L2.2 5.8l4-.6L8 1.5z"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  {
    key: 'roles',
    labelKey: 'settings.tab.roles',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="5" r="2.5" stroke="currentColor" strokeWidth="1.4" />
        <path
          d="M3 13c0-2.5 2.2-4 5-4s5 1.5 5 4"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    key: 'soul',
    labelKey: 'settings.tab.soul',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <path
          d="M8 13.5S2.5 10 2.5 6A2.5 2.5 0 018 4a2.5 2.5 0 015.5 2c0 4-5.5 7.5-5.5 7.5z"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  {
    key: 'projects',
    labelKey: 'settings.tab.projects',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <path
          d="M2 4.5A1.5 1.5 0 013.5 3H6l1.5 1.5h5A1.5 1.5 0 0114 6v5.5A1.5 1.5 0 0112.5 13h-9A1.5 1.5 0 012 11.5v-7z"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinejoin="round"
        />
      </svg>
    ),
  },
  {
    key: 'schedules',
    labelKey: 'settings.tab.schedules',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="9" r="5" stroke="currentColor" strokeWidth="1.3" />
        <path
          d="M8 6.5V9l1.8 1M5.5 2.5l-2 1.5M10.5 2.5l2 1.5"
          stroke="currentColor"
          strokeWidth="1.3"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    key: 'connections',
    labelKey: 'settings.tab.connections',
    icon: (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
        <circle cx="4" cy="8" r="2" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="12" cy="8" r="2" stroke="currentColor" strokeWidth="1.5" />
        <path d="M6 8h4" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    ),
  },
]

export function SettingsModal({ onClose }: Props) {
  const { t } = useTranslation()
  const initialTab = useUiStore((s) => s.settingsTab)
  // modal 每次開啟才 mount(條件渲染),init 時 settingsTab 已被 openSettings 設好
  const [tab, setTab] = useState<Tab>(() =>
    TABS.some((x) => x.key === initialTab) ? (initialTab as Tab) : 'general',
  )

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-[2px] animate-fade-in p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl h-[600px] max-h-[85vh] bg-claude-cream rounded-2xl shadow-modal flex overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="w-52 shrink-0 bg-claude-panel/70 border-r border-claude-border/60 flex flex-col">
          <div className="px-4 pt-5 pb-3 text-[15px] font-semibold">
            {t('settings.title')}
          </div>
          <nav className="flex-1 px-2 space-y-0.5">
            {TABS.map((tabItem) => (
              <button
                key={tabItem.key}
                className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-[13px] text-left transition-colors ${
                  tab === tabItem.key
                    ? 'bg-claude-borderSoft text-claude-text font-medium'
                    : 'text-claude-textDim hover:bg-claude-borderSoft/60 hover:text-claude-text'
                }`}
                onClick={() => setTab(tabItem.key)}
              >
                <span className="text-claude-textDim">{tabItem.icon}</span>
                {t(tabItem.labelKey)}
              </button>
            ))}
          </nav>
        </div>

        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex items-center justify-between px-5 py-3 border-b border-claude-border/60">
            <div className="text-[15px] font-medium">
              {(() => {
                const active = TABS.find((x) => x.key === tab)
                return active ? t(active.labelKey) : ''
              })()}
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-claude-textDim hover:bg-claude-panel hover:text-claude-text transition-colors"
              aria-label={t('common.close')}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path
                  d="M4 4l8 8M12 4l-8 8"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {tab === 'general' && <SettingsPanel />}
            {tab === 'models' && <ModelSettingsPanel />}
            {tab === 'memory' && <MemoryPanel />}
            {tab === 'skills' && <SkillsPanel />}
            {tab === 'roles' && <RolesPanel />}
            {tab === 'soul' && <SoulPanel />}
            {tab === 'projects' && <ProjectsPanel />}
            {tab === 'schedules' && <SchedulesPanel />}
            {tab === 'connections' && (
              <>
                <div className="p-6 border-b border-claude-border/60">
                  <McpServersPanel />
                </div>
                <ConnectionsPanel />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
