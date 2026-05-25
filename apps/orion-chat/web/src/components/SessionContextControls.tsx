import { useEffect, useState } from 'react'
import { apiFetch } from '../api/client'
import { useTranslation } from '../i18n'

interface RoleSummary {
  name: string
}
interface ProjectSummary {
  id: string
  name: string
}

const selectCls =
  'px-2 py-0.5 rounded-md text-[12px] bg-claude-panel text-claude-textDim hover:text-claude-text border border-claude-border focus:outline-none focus:border-claude-orange max-w-[8rem]'

/**
 * 每個 session 選 active role / project — 改變立即 PUT,下一輪 turn 的 system
 * prompt 會帶上 role body / project 指令(見 chat.py runner)。
 */
export function SessionContextControls({ sessionId }: { sessionId: string }) {
  const { t } = useTranslation()
  const [roles, setRoles] = useState<RoleSummary[]>([])
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [role, setRole] = useState('')
  const [projectId, setProjectId] = useState('')

  useEffect(() => {
    let alive = true
    void Promise.all([
      apiFetch<RoleSummary[]>('/roles').catch(() => []),
      apiFetch<ProjectSummary[]>('/projects').catch(() => []),
      apiFetch<{ role: string | null }>(`/sessions/${sessionId}/role`).catch(
        () => ({ role: null }),
      ),
      apiFetch<{ project_id: string | null }>(
        `/sessions/${sessionId}/project`,
      ).catch(() => ({ project_id: null })),
    ]).then(([rs, ps, r, p]) => {
      if (!alive) return
      setRoles(rs)
      setProjects(ps)
      setRole(r.role ?? '')
      setProjectId(p.project_id ?? '')
    })
    return () => {
      alive = false
    }
  }, [sessionId])

  function changeRole(next: string) {
    setRole(next)
    void apiFetch(`/sessions/${sessionId}/role`, {
      method: 'PUT',
      body: { role: next || null },
    }).catch(() => {})
  }

  function changeProject(next: string) {
    setProjectId(next)
    void apiFetch(`/sessions/${sessionId}/project`, {
      method: 'PUT',
      body: { project_id: next || null },
    }).catch(() => {})
  }

  return (
    <>
      {roles.length > 0 && (
        <select
          className={selectCls}
          value={role}
          onChange={(e) => changeRole(e.target.value)}
          title={t('chat.role.title')}
        >
          <option value="">{t('chat.role.none')}</option>
          {roles.map((r) => (
            <option key={r.name} value={r.name}>
              {r.name}
            </option>
          ))}
        </select>
      )}
      {projects.length > 0 && (
        <select
          className={selectCls}
          value={projectId}
          onChange={(e) => changeProject(e.target.value)}
          title={t('chat.project.title')}
        >
          <option value="">{t('chat.project.none')}</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      )}
    </>
  )
}
