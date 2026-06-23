// Tasks & risks: everything Shlomi is tracking. Tasks as a status kanban (with
// dependency awareness), and panels for risks, open questions, and decisions.
// Any item opens the entity drawer with its full provenance.

import { AlertTriangle, GitBranch, HelpCircle, Lightbulb, LayoutGrid } from 'lucide-react'
import { useState } from 'react'
import { EntityDrawer, type EntitySelection } from '../components/board/EntityDrawer'
import { PageContainer, PageHeader } from '../components/PageHeader'
import { Card, CardHeader, EmptyState, ErrorState, Avatar, Skeleton, StatusBadge } from '../components/ui'
import { BUCKETS, buildBoard, type TaskItem } from '../lib/board'
import { fmtDate, personLabel, relativeDue, severity, taskStatus, toneClasses, questionStatus } from '../lib/format'
import { AGENT_NAME } from '../lib/persona'
import { useProjectState } from '../lib/queries'
import type { Entity, EntityType } from '../lib/types'

export function Board() {
  const { data: state, isLoading, isError, refetch, isFetching } = useProjectState({ poll: true })
  const [sel, setSel] = useState<EntitySelection | null>(null)
  const open = (type: EntityType, id: string, entity: Entity) => setSel({ type, id, entity })

  const board = buildBoard(state)
  const risks = Object.entries(state?.Risk ?? {})
  const questions = Object.entries(state?.OpenQuestion ?? {})
  const decisions = Object.entries(state?.Decision ?? {})
  const totalTasks = Object.keys(state?.Task ?? {}).length

  if (isLoading) {
    return (
      <PageContainer>
        <PageHeader eyebrow="Project" title="Tasks & risks" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-64 w-full" />
          ))}
        </div>
      </PageContainer>
    )
  }

  if (isError) {
    return (
      <PageContainer>
        <PageHeader eyebrow="Project" title="Tasks & risks" />
        <Card>
          <ErrorState
            description={`${AGENT_NAME} couldn't load the project state.`}
            onRetry={() => refetch()}
            retrying={isFetching}
          />
        </Card>
      </PageContainer>
    )
  }

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Project"
        title="Tasks & risks"
        subtitle={`Everything ${AGENT_NAME} is tracking, derived from the event log. Click anything to see how it knows.`}
      />

      {totalTasks === 0 ? (
        <Card>
          <EmptyState
            icon={LayoutGrid}
            title="No tasks yet"
            description={`Feed ${AGENT_NAME} a transcript or note and tasks will appear here as it extracts them.`}
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {BUCKETS.map((b) => (
            <div key={b.key} className="flex min-w-0 flex-col">
              <div className="mb-2.5 flex items-center gap-2 px-1">
                <span className={`size-2.5 rounded-full ${toneClasses(b.tone).dot}`} />
                <h2 className="text-[13px] font-bold text-ink">{b.label}</h2>
                <span className="text-[12px] font-semibold text-faint">{board[b.key].length}</span>
              </div>
              <div className="flex flex-col gap-2.5">
                {board[b.key].length === 0 ? (
                  <div className="rounded-xl border border-dashed border-line py-6 text-center text-[12px] text-faint">
                    Empty
                  </div>
                ) : (
                  board[b.key].map((t) => (
                    <TaskCard key={t.id} item={t} onOpen={() => open('Task', t.id, t.entity)} />
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mt-7 grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader icon={AlertTriangle} title="Risks" count={risks.length} />
          <div className="flex flex-col">
            {risks.length === 0 ? (
              <p className="px-5 pb-5 text-[13px] text-muted">No risks tracked.</p>
            ) : (
              risks.map(([id, e]) => (
                <button
                  key={id}
                  onClick={() => open('Risk', id, e)}
                  className="flex items-start gap-3 border-t border-line-2 px-5 py-3 text-left transition-colors first:border-t-0 hover:bg-surface-2"
                >
                  <StatusBadge status={severity(e.fields.severity)} className="mt-0.5" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-medium leading-snug text-ink">
                      {e.fields.description || e.fields.title || id}
                    </span>
                    <span className="mt-0.5 block text-[12px] text-muted">{personLabel(e.fields.owner)}</span>
                  </span>
                </button>
              ))
            )}
          </div>
        </Card>

        <Card>
          <CardHeader icon={HelpCircle} title="Open questions" count={questions.length} />
          <div className="flex flex-col">
            {questions.length === 0 ? (
              <p className="px-5 pb-5 text-[13px] text-muted">Nothing open.</p>
            ) : (
              questions.map(([id, e]) => (
                <button
                  key={id}
                  onClick={() => open('OpenQuestion', id, e)}
                  className="flex items-start gap-3 border-t border-line-2 px-5 py-3 text-left transition-colors first:border-t-0 hover:bg-surface-2"
                >
                  <StatusBadge status={questionStatus(e.fields.status)} className="mt-0.5" />
                  <span className="min-w-0 flex-1 text-[13px] font-medium leading-snug text-ink">
                    {e.fields.description || e.fields.title || id}
                  </span>
                </button>
              ))
            )}
          </div>
        </Card>

        <Card>
          <CardHeader icon={Lightbulb} title="Decisions" count={decisions.length} />
          <div className="flex flex-col">
            {decisions.length === 0 ? (
              <p className="px-5 pb-5 text-[13px] text-muted">No decisions recorded.</p>
            ) : (
              decisions.map(([id, e]) => (
                <button
                  key={id}
                  onClick={() => open('Decision', id, e)}
                  className="flex items-start gap-3 border-t border-line-2 px-5 py-3 text-left transition-colors first:border-t-0 hover:bg-surface-2"
                >
                  <span className="mt-1 size-2 shrink-0 rounded-full bg-teal" />
                  <span className="min-w-0 flex-1 text-[13px] font-medium leading-snug text-ink">
                    {e.fields.description || e.fields.title || id}
                  </span>
                </button>
              ))
            )}
          </div>
        </Card>
      </div>

      <EntityDrawer selection={sel} onClose={() => setSel(null)} />
    </PageContainer>
  )
}

function TaskCard({ item, onOpen }: { item: TaskItem; onOpen: () => void }) {
  const f = item.entity.fields
  const due = relativeDue(f.due_date)
  return (
    <button
      onClick={onOpen}
      className="group rounded-xl border border-line bg-surface p-3.5 text-left shadow-card-sm transition-all hover:-translate-y-0.5 hover:shadow-card"
    >
      <p className="text-[13px] font-semibold leading-snug text-ink">{f.title || item.id}</p>
      <div className="mt-2.5 flex items-center gap-2">
        <StatusBadge status={taskStatus(f.status)} />
        {due.label && (
          <span className={`text-[11.5px] font-medium ${due.overdue ? 'text-red' : due.soon ? 'text-amber' : 'text-faint'}`}>
            {fmtDate(f.due_date)}
          </span>
        )}
        {(f.owner ?? f.assignee) && <Avatar name={f.owner ?? f.assignee} size="xs" className="ml-auto" />}
      </div>
      {item.blockedBy.length > 0 && (
        <div className="mt-2.5 flex items-center gap-1.5 rounded-lg bg-red-soft px-2 py-1 text-[11px] font-medium text-red">
          <GitBranch className="size-3" />
          Waiting on {item.blockedBy.length === 1 ? item.blockedBy[0] : `${item.blockedBy.length} tasks`}
        </div>
      )}
    </button>
  )
}
