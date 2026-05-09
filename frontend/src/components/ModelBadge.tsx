import type { ModelCatalog } from '../types/events'

interface Props {
  provider: string | null | undefined
  model: string | null | undefined
  catalog: ModelCatalog | null
}

/** 唯讀小 pill — header 顯示當前 session 的 model。點不開,要切請新建對話。 */
export function ModelBadge({ provider, model, catalog }: Props) {
  if (!provider || !model) return null

  const label = catalog
    ? findLabel(catalog, provider, model) ?? model
    : model

  return (
    <span
      className="text-[12px] text-claude-textDim px-2 py-0.5 rounded-md bg-claude-panel cursor-default select-none"
      title="Start a new chat to change model"
    >
      {label}
    </span>
  )
}

function findLabel(
  catalog: ModelCatalog,
  provider: string,
  model: string,
): string | null {
  const p = catalog.providers.find((p) => p.id === provider)
  if (!p) return null
  const m = p.models.find((m) => m.id === model)
  return m?.label ?? null
}
