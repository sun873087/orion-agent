/**
 * Permissions(allowlist / denylist)管理 — Claude Code 風 pattern。
 *
 * Scope:Global(`~/.orion/permissions.json`)+ Project
 *   (`<workspace>/.orion/permissions.json`,只有 projectId 傳進來才顯)
 * Pattern 範例:
 *   - Bash(uv run *)
 *   - WebFetch(domain:docs.anthropic.com)
 *   - Read(/tmp/**)
 *   - WebSearch          (無 parens = 任何 input 都 match)
 */
import { useEffect, useState } from 'react'
import { CheckCircle2, Plus, ShieldOff, Trash2 } from 'lucide-react'

import {
  getPermissions,
  getProject,
  setPermissions,
  type PermissionPolicy,
  type PermissionScope,
} from '../../api/agent'
import { useTranslation } from '../../i18n'

export function PermissionsSection({ projectId }: { projectId?: string | null } = {}) {
  const { t } = useTranslation()
  const [scope, setScope] = useState<PermissionScope>('global')
  const [workspaceDir, setWorkspaceDir] = useState<string | null>(null)
  const [policy, setPolicy] = useState<PermissionPolicy>({ scope: 'global', allow: [], deny: [] })
  const [busy, setBusy] = useState(false)

  // projectId 變動 → 取 workspace_dir;若無就退回 global scope
  useEffect(() => {
    if (!projectId) {
      setWorkspaceDir(null)
      setScope('global')
      return
    }
    getProject(projectId).then((r) => {
      setWorkspaceDir(r?.project.workspace_dir ?? null)
    })
  }, [projectId])

  // scope / workspaceDir 變動 → reload policy
  useEffect(() => {
    let cancelled = false
    setBusy(true)
    getPermissions(scope, scope === 'project' ? workspaceDir : null)
      .then((p) => {
        if (!cancelled) setPolicy(p)
      })
      .finally(() => {
        if (!cancelled) setBusy(false)
      })
    return () => {
      cancelled = true
    }
  }, [scope, workspaceDir])

  async function persist(next: PermissionPolicy) {
    setPolicy(next)
    setBusy(true)
    try {
      await setPermissions(
        scope,
        next.allow,
        next.deny,
        scope === 'project' ? workspaceDir : null,
      )
    } finally {
      setBusy(false)
    }
  }

  function addPattern(kind: 'allow' | 'deny', pattern: string) {
    const trimmed = pattern.trim()
    if (!trimmed) return
    const list = kind === 'allow' ? policy.allow : policy.deny
    if (list.includes(trimmed)) return
    const next: PermissionPolicy = {
      ...policy,
      [kind]: [...list, trimmed],
    }
    void persist(next)
  }

  function removePattern(kind: 'allow' | 'deny', idx: number) {
    const list = kind === 'allow' ? policy.allow : policy.deny
    const next: PermissionPolicy = {
      ...policy,
      [kind]: list.filter((_, i) => i !== idx),
    }
    void persist(next)
  }

  const projectAvailable = !!projectId && !!workspaceDir

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-fg-muted">
        {t('permissions.description')}
      </p>

      {projectAvailable && (
        <div className="flex gap-1 self-start rounded-lg border border-bg-hover bg-bg-panel p-1">
          <ScopeTab
            active={scope === 'global'}
            onClick={() => setScope('global')}
            label={t('permissions.scope.global')}
          />
          <ScopeTab
            active={scope === 'project'}
            onClick={() => setScope('project')}
            label={t('permissions.scope.project')}
          />
        </div>
      )}

      <PatternList
        kind="allow"
        title={t('permissions.allow.title')}
        hint={t('permissions.allow.hint')}
        icon={CheckCircle2}
        iconColor="text-success"
        patterns={policy.allow}
        onAdd={(p) => addPattern('allow', p)}
        onRemove={(i) => removePattern('allow', i)}
        addPlaceholder={t('permissions.addAllow.placeholder')}
        disabled={busy}
      />

      <PatternList
        kind="deny"
        title={t('permissions.deny.title')}
        hint={t('permissions.deny.hint')}
        icon={ShieldOff}
        iconColor="text-error"
        patterns={policy.deny}
        onAdd={(p) => addPattern('deny', p)}
        onRemove={(i) => removePattern('deny', i)}
        addPlaceholder={t('permissions.addDeny.placeholder')}
        disabled={busy}
      />

      <details className="text-xs text-fg-muted">
        <summary className="cursor-pointer hover:text-fg-base">
          {t('permissions.examples.title')}
        </summary>
        <pre className="mt-2 rounded-md bg-bg-panel p-3 font-mono text-[11px] leading-relaxed">
{`Bash(uv run *)
Bash(npm test *)
WebFetch(domain:docs.anthropic.com)
WebFetch(domain:*.openai.com)
Read(/tmp/**)
Grep
WebSearch`}
        </pre>
      </details>
    </div>
  )
}

function ScopeTab({
  active,
  onClick,
  label,
}: {
  active: boolean
  onClick: () => void
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
        active
          ? 'bg-accent text-white'
          : 'text-fg-muted hover:bg-bg-hover hover:text-fg-base'
      }`}
    >
      {label}
    </button>
  )
}

function PatternList({
  title,
  hint,
  icon: Icon,
  iconColor,
  patterns,
  onAdd,
  onRemove,
  addPlaceholder,
  disabled,
}: {
  kind: 'allow' | 'deny'
  title: string
  hint: string
  icon: typeof CheckCircle2
  iconColor: string
  patterns: string[]
  onAdd: (p: string) => void
  onRemove: (idx: number) => void
  addPlaceholder: string
  disabled: boolean
}) {
  const [draft, setDraft] = useState('')

  function submit() {
    if (!draft.trim()) return
    onAdd(draft.trim())
    setDraft('')
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Icon size={14} className={iconColor} />
        <h3 className="text-sm font-medium">{title}</h3>
      </div>
      <p className="text-[11px] text-fg-subtle">{hint}</p>
      <ul className="flex flex-col gap-1">
        {patterns.map((p, i) => (
          <li
            key={i}
            className="flex items-center justify-between rounded-md border border-bg-hover bg-bg-panel px-3 py-1.5"
          >
            <code className="truncate font-mono text-[11px] text-fg-base">{p}</code>
            <button
              type="button"
              onClick={() => onRemove(i)}
              disabled={disabled}
              title="Remove"
              className="rounded p-0.5 text-fg-subtle hover:bg-error/15 hover:text-error disabled:opacity-40"
            >
              <Trash2 size={12} />
            </button>
          </li>
        ))}
        {patterns.length === 0 && (
          <li className="text-[11px] italic text-fg-subtle">(empty)</li>
        )}
      </ul>
      <div className="flex gap-1.5">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              submit()
            }
          }}
          placeholder={addPlaceholder}
          disabled={disabled}
          className="flex-1 rounded-md border border-bg-hover bg-bg-input px-3 py-1.5 font-mono text-xs focus:border-accent focus:outline-none disabled:opacity-40"
        />
        <button
          type="button"
          onClick={submit}
          disabled={disabled || !draft.trim()}
          className="flex items-center gap-1 rounded-md bg-bg-hover px-2.5 text-xs hover:bg-bg-hover/70 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Plus size={12} />
          <span>Add</span>
        </button>
      </div>
    </div>
  )
}
