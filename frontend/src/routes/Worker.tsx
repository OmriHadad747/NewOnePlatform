// Team-member view: a focused, calm "what do I need to do" screen. The things
// Shlomi is waiting on from me (threads where its last word needs my reply),
// and my own tasks. Replying here posts a message on the thread as me — the
// same channel a worker would answer Shlomi on for real.

import { CheckCircle2, Inbox, Send, Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import { EntityDrawer, type EntitySelection } from '../components/board/EntityDrawer'
import { PageContainer, PageHeader } from '../components/PageHeader'
import { useToast } from '../components/Toast'
import { Button, Card, CardHeader, EmptyState, Skeleton, StatusBadge } from '../components/ui'
import { fmtDate, personLabel, relativeDue, taskStatus } from '../lib/format'
import { AGENT_NAME, usePersona } from '../lib/persona'
import { useAddRawEvent, useEvents, useProject, useProjectState, useProposals } from '../lib/queries'
import { reconstructThreads, threadTitle } from '../lib/threads'
import type { Entity, EntityType } from '../lib/types'

export function Worker() {
  const { persona } = usePersona()
  const { data: project } = useProject()
  const { data: state, isLoading } = useProjectState({ poll: true })
  const { data: events } = useEvents({ poll: true })
  const { data: proposals } = useProposals({ poll: true })
  const me = persona.identity || project?.team?.[0] || ''

  const myTasks = useMemo(
    () => Object.entries(state?.Task ?? {}).filter(([, e]) => (e.fields.owner ?? e.fields.assignee) === me),
    [state, me],
  )

  // Threads that genuinely need me: I'm a participant, Shlomi spoke last, and
  // either it has an open proposal or its last message actually asks something
  // (so a closing "thanks" doesn't masquerade as an open question).
  const waiting = useMemo(
    () =>
      reconstructThreads(events ?? [], proposals ?? [])
        .filter((t) => t.participants.includes(me))
        .filter((t) => {
          const last = t.messages[t.messages.length - 1]
          return last?.isAgent && (t.open || /\?/.test(last.text))
        }),
    [events, proposals, me],
  )

  const [sel, setSel] = useState<EntitySelection | null>(null)
  const open = (type: EntityType, id: string, entity: Entity) => setSel({ type, id, entity })

  return (
    <PageContainer>
      <PageHeader
        eyebrow="My work"
        title={me ? `Hi, ${personLabel(me)}` : 'My work'}
        subtitle={`What ${AGENT_NAME} needs from you, and the tasks on your plate.`}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section className="min-w-0">
          <h2 className="mb-3 flex items-center gap-2 text-[13px] font-bold uppercase tracking-wide text-faint">
            <Inbox className="size-4" /> {AGENT_NAME} needs you
            {waiting.length > 0 && (
              <span className="rounded-full bg-accent px-1.5 text-[11px] font-bold text-accent-ink">{waiting.length}</span>
            )}
          </h2>
          {waiting.length === 0 ? (
            <Card>
              <EmptyState
                icon={CheckCircle2}
                title="You're all caught up"
                description={`${AGENT_NAME} has no open questions for you right now.`}
              />
            </Card>
          ) : (
            <div className="flex flex-col gap-4">
              {waiting.map((t) => (
                <AskCard key={t.id} thread={t} me={me} />
              ))}
            </div>
          )}
        </section>

        <aside>
          <Card>
            <CardHeader title="My tasks" count={myTasks.length} />
            <div className="flex flex-col">
              {isLoading ? (
                <div className="space-y-2 p-4">
                  <Skeleton className="h-12 w-full" />
                  <Skeleton className="h-12 w-full" />
                </div>
              ) : myTasks.length === 0 ? (
                <p className="px-5 pb-5 text-[13px] text-muted">No tasks assigned to you.</p>
              ) : (
                myTasks.map(([id, e]) => {
                  const due = relativeDue(e.fields.due_date)
                  return (
                    <button
                      key={id}
                      onClick={() => open('Task', id, e)}
                      className="flex flex-col gap-2 border-t border-line-2 px-5 py-3 text-left transition-colors first:border-t-0 hover:bg-surface-2"
                    >
                      <span className="text-[13px] font-semibold leading-snug text-ink">{e.fields.title || id}</span>
                      <span className="flex items-center gap-2">
                        <StatusBadge status={taskStatus(e.fields.status)} />
                        {due.label && (
                          <span className={`text-[11.5px] font-medium ${due.overdue ? 'text-red' : due.soon ? 'text-amber' : 'text-faint'}`}>
                            Due {fmtDate(e.fields.due_date)}
                          </span>
                        )}
                      </span>
                    </button>
                  )
                })
              )}
            </div>
          </Card>
        </aside>
      </div>

      <EntityDrawer selection={sel} onClose={() => setSel(null)} />
    </PageContainer>
  )
}

function AskCard({ thread, me }: { thread: ReturnType<typeof reconstructThreads>[number]; me: string }) {
  const last = thread.messages[thread.messages.length - 1]
  const reply = useAddRawEvent()
  const toast = useToast()
  const [draft, setDraft] = useState('')

  const send = async () => {
    const text = draft.trim()
    if (!text) return
    try {
      await reply.mutateAsync({ type: 'message_received', text, source: me, channel: 'stub', thread_id: thread.id })
      setDraft('')
      toast.success('Reply sent', `${AGENT_NAME} has your answer.`)
    } catch {
      toast.error(`${AGENT_NAME} didn't get that`, 'Your reply could not be sent. Try again.', {
        label: 'Retry',
        onClick: send,
      })
    }
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex items-start gap-3 p-5">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
          <Sparkles className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-bold text-ink">{threadTitle(thread)}</p>
          <p className="mt-1.5 rounded-xl bg-surface-2 px-3.5 py-2.5 text-[13px] leading-relaxed text-ink-soft">
            {last?.text}
          </p>
          <div className="mt-3 flex items-end gap-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
              rows={1}
              placeholder="Reply to Shlomi…"
              className="max-h-28 min-h-10 flex-1 resize-none rounded-xl border border-line bg-surface px-3 py-2.5 text-[13.5px] text-ink outline-none transition-colors placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/30"
            />
            <Button variant="primary" icon={Send} loading={reply.isPending} disabled={!draft.trim()} onClick={send}>
              Send
            </Button>
          </div>
        </div>
      </div>
    </Card>
  )
}
