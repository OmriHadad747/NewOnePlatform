// Conversations between Shlomi and the team. A list of threads on the left,
// the selected conversation as chat bubbles on the right — Shlomi on one side,
// the person on the other. This is where approvals and clarifications actually
// happen (a reply on a thread is how a human approves).

import { MessagesSquare, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { PageContainer, PageHeader } from '../components/PageHeader'
import { Avatar, Card, EmptyState, ErrorState, Skeleton, Tag } from '../components/ui'
import { cn } from '../lib/cn'
import { fmtTime, personLabel } from '../lib/format'
import { AGENT_NAME } from '../lib/persona'
import { useEvents, useProposals } from '../lib/queries'
import { reconstructThreads, threadTitle, type Thread } from '../lib/threads'

export function Threads() {
  const { data: events, isLoading, isError, refetch, isFetching } = useEvents({ poll: true })
  const { data: proposals } = useProposals({ poll: true })
  const threads = useMemo(
    () => reconstructThreads(events ?? [], proposals ?? []),
    [events, proposals],
  )
  const [activeId, setActiveId] = useState<string | null>(null)
  useEffect(() => {
    if (!activeId && threads.length) setActiveId(threads[0].id)
  }, [threads, activeId])
  const active = threads.find((t) => t.id === activeId) ?? null

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Project"
        title="Threads"
        subtitle={`Conversations between ${AGENT_NAME} and the team — the channel where approvals and clarifications happen.`}
      />

      {isLoading ? (
        <Skeleton className="h-[60vh] w-full" />
      ) : isError ? (
        <Card>
          <ErrorState description={`${AGENT_NAME} couldn't load conversations.`} onRetry={() => refetch()} retrying={isFetching} />
        </Card>
      ) : threads.length === 0 ? (
        <Card>
          <EmptyState
            icon={MessagesSquare}
            title="No conversations yet"
            description={`When ${AGENT_NAME} reaches out for a status update or an approval, the thread shows up here.`}
          />
        </Card>
      ) : (
        <Card className="grid grid-cols-1 overflow-hidden md:grid-cols-[300px_minmax(0,1fr)] md:min-h-[60vh]">
          <ul className="border-line md:border-r">
            {threads.map((t) => (
              <li key={t.id}>
                <button
                  onClick={() => setActiveId(t.id)}
                  className={cn(
                    'flex w-full flex-col gap-1 border-b border-line-2 px-4 py-3 text-left transition-colors',
                    t.id === activeId ? 'bg-accent-soft' : 'hover:bg-surface-2',
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-[13px] font-bold text-ink">{threadTitle(t)}</span>
                    {t.open && <Tag tone="amber">Open</Tag>}
                  </div>
                  <span className="truncate text-[12px] text-muted">
                    {t.participants.map(personLabel).join(', ') || 'Shlomi'} · {t.messages.length} messages
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {active ? <Conversation thread={active} /> : null}
        </Card>
      )}
    </PageContainer>
  )
}

function Conversation({ thread }: { thread: Thread }) {
  return (
    <div className="flex max-h-[70vh] flex-col">
      <div className="flex items-center gap-2 border-b border-line px-5 py-3.5">
        <h2 className="min-w-0 flex-1 truncate text-[14px] font-bold text-ink">{threadTitle(thread)}</h2>
        {thread.open && <Tag tone="amber" dot>Awaiting reply</Tag>}
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto bg-grain p-5">
        {thread.messages.map((m, i) => (
          <div key={`${m.timestamp}-${m.sender}-${i}`} className={cn('flex max-w-[80%] gap-2.5', m.isAgent ? 'self-start' : 'flex-row-reverse self-end')}>
            {m.isAgent ? (
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
                <Sparkles className="size-4" />
              </span>
            ) : (
              <Avatar name={m.sender} size="md" />
            )}
            <div>
              <div
                className={cn(
                  'rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed shadow-card-sm',
                  m.isAgent
                    ? 'rounded-tl-sm bg-surface text-ink'
                    : 'rounded-tr-sm bg-accent text-accent-ink',
                )}
              >
                {m.subject && m.isAgent && <p className="mb-1 text-[12px] font-bold opacity-80">{m.subject}</p>}
                {m.text}
              </div>
              <p className={cn('mt-1 text-[10.5px] text-faint', m.isAgent ? 'text-left' : 'text-right')}>
                {m.isAgent ? AGENT_NAME : personLabel(m.sender)} · {fmtTime(m.timestamp)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
