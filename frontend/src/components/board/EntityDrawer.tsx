// Inspect one tracked entity: its current fields, plus the provenance history —
// who asserted each change, when, and the verbatim source span that justified
// it. The history is a core differentiator: every fact is traceable to its
// origin in the event log.

import { Quote } from 'lucide-react'
import {
  avatarTone,
  fmtDate,
  fmtTime,
  personLabel,
  severity,
  taskStatus,
  titlecase,
  toneClasses,
} from '../../lib/format'
import type { Entity, EntityType } from '../../lib/types'
import { Drawer } from '../Drawer'
import { Avatar, StatusBadge, Tag } from '../ui'

export interface EntitySelection {
  type: EntityType
  id: string
  entity: Entity
}

// Fields rendered inline as their own chips; the rest fall to a generic list.
const SPECIAL = new Set(['title', 'name', 'description', 'status', 'severity', 'owner', 'assignee', 'due_date'])

function FieldChips({ type, fields }: { type: EntityType; fields: Record<string, any> }) {
  return (
    <div className="flex flex-wrap gap-2">
      {fields.status != null &&
        (type === 'Task' ? (
          <StatusBadge status={taskStatus(fields.status)} />
        ) : (
          <Tag tone="muted">{titlecase(fields.status)}</Tag>
        ))}
      {fields.severity != null && <StatusBadge status={severity(fields.severity)} />}
      {(fields.owner ?? fields.assignee) != null && (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2 py-0.5 text-[12px] font-semibold text-ink-soft">
          <Avatar name={fields.owner ?? fields.assignee} size="xs" />
          {personLabel(fields.owner ?? fields.assignee)}
        </span>
      )}
      {fields.due_date != null && <Tag tone="amber">Due {fmtDate(fields.due_date)}</Tag>}
    </div>
  )
}

export function EntityDrawer({
  selection,
  onClose,
}: {
  selection: EntitySelection | null
  onClose: () => void
}) {
  const fields = selection?.entity.fields ?? {}
  const history = selection?.entity.history ?? []
  const title = fields.title || fields.description || fields.name || selection?.id || ''
  const extra = Object.entries(fields).filter(([k]) => !SPECIAL.has(k))

  return (
    <Drawer open={!!selection} onClose={onClose}>
      {selection && (
        <div className="p-6">
          <Tag tone="accent">{selection.type}</Tag>
          <h2 className="mt-3 pr-8 text-[19px] font-extrabold leading-snug tracking-tight text-ink">
            {title}
          </h2>

          <div className="mt-4">
            <FieldChips type={selection.type} fields={fields} />
          </div>

          {fields.description && fields.description !== title && (
            <p className="mt-4 text-[13.5px] leading-relaxed text-ink-soft">{fields.description}</p>
          )}

          {extra.length > 0 && (
            <dl className="mt-5 divide-y divide-line-2 rounded-xl border border-line">
              {extra.map(([k, v]) => (
                <div key={k} className="flex gap-3 px-3.5 py-2.5">
                  <dt className="w-28 shrink-0 text-[12px] font-semibold uppercase tracking-wide text-faint">
                    {titlecase(k)}
                  </dt>
                  <dd className="min-w-0 flex-1 text-[13px] text-ink-soft">
                    {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                  </dd>
                </div>
              ))}
            </dl>
          )}

          <h3 className="mb-3 mt-7 text-[12px] font-bold uppercase tracking-wide text-faint">
            How Shlomi knows this · {history.length} {history.length === 1 ? 'record' : 'records'}
          </h3>
          <ol className="relative ml-1 space-y-4 border-l border-line pl-5">
            {history.length === 0 && <li className="text-[13px] text-muted">No provenance recorded.</li>}
            {history
              .slice()
              .reverse()
              .map((h, i) => {
                const c = toneClasses(avatarTone(h.asserted_by))
                return (
                  <li key={i} className="relative">
                    <span className={`absolute -left-[27px] top-1 size-2.5 rounded-full ${c.dot}`} />
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-bold text-ink">{personLabel(h.asserted_by)}</span>
                      <span className="text-[11px] tabular text-faint">{fmtTime(h.asserted_at)}</span>
                    </div>
                    {Object.keys(h.fields_changed ?? {}).length > 0 && (
                      <p className="mt-1 text-[12.5px] text-muted">
                        Set{' '}
                        {Object.entries(h.fields_changed)
                          .map(([k, v]) => `${k} → ${typeof v === 'object' ? JSON.stringify(v) : v}`)
                          .join(', ')}
                      </p>
                    )}
                    {h.source_span && (
                      <p className="mt-1.5 flex gap-1.5 rounded-lg bg-surface-2 px-2.5 py-1.5 text-[12px] italic leading-snug text-ink-soft">
                        <Quote className="size-3.5 shrink-0 text-faint" />
                        {h.source_span}
                      </p>
                    )}
                  </li>
                )
              })}
          </ol>
        </div>
      )}
    </Drawer>
  )
}
