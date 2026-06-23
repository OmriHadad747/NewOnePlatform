// The full event log, as it happened — the append-only source of truth this
// whole system is built on, made legible. Grouped by day, newest first, with a
// type filter. Each row shows what happened, who, and when.

import { useMemo, useState } from 'react'
import { PageContainer, PageHeader } from '../components/PageHeader'
import { Card, EmptyState, ErrorState, Mono, Skeleton } from '../components/ui'
import { cn } from '../lib/cn'
import { describeEvent, groupByDay } from '../lib/events'
import { eventView, fmtTime, toneClasses } from '../lib/format'
import { AGENT_NAME } from '../lib/persona'
import { useEvents } from '../lib/queries'
import { History } from 'lucide-react'

type Filter = 'all' | 'proposals' | 'approvals' | 'messages'

const FILTERS: { key: Filter; label: string; match: (t: string) => boolean }[] = [
  { key: 'all', label: 'All', match: () => true },
  { key: 'proposals', label: 'Proposals', match: (t) => t === 'agent_proposal' || t === 'proposal_rejected' },
  { key: 'approvals', label: 'Approvals', match: (t) => t === 'human_approval' },
  {
    key: 'messages',
    label: 'Messages',
    match: (t) => ['message_sent', 'message_received', 'ticket_opened', 'flag_raised', 'report_to_management'].includes(t),
  },
]

export function Timeline() {
  const { data: events, isLoading, isError, refetch, isFetching } = useEvents({ poll: true })
  const [filter, setFilter] = useState<Filter>('all')

  const groups = useMemo(() => {
    const match = FILTERS.find((f) => f.key === filter)!.match
    return groupByDay((events ?? []).filter((e) => match(e.type)))
  }, [events, filter])

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Project"
        title="Timeline"
        subtitle="The append-only event log — the single source of truth all project state is derived from."
        actions={
          <div className="flex gap-1 rounded-xl border border-line bg-surface p-1">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={cn(
                  'rounded-lg px-3 py-1.5 text-[12.5px] font-semibold transition-colors',
                  filter === f.key ? 'bg-accent-soft text-accent' : 'text-ink-soft hover:bg-surface-2',
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
        }
      />

      {isLoading ? (
        <div className="flex flex-col gap-3">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : isError ? (
        <Card>
          <ErrorState
            description={`${AGENT_NAME} couldn't load the event log.`}
            onRetry={() => refetch()}
            retrying={isFetching}
          />
        </Card>
      ) : groups.length === 0 ? (
        <Card>
          <EmptyState icon={History} title="Nothing here yet" description="Events will stream in as work happens." />
        </Card>
      ) : (
        <div className="flex flex-col gap-7">
          {groups.map((g) => (
            <div key={g.day}>
              <div className="mb-3 flex items-center gap-3">
                <h2 className="text-[13px] font-bold uppercase tracking-wide text-faint">{g.label}</h2>
                <span className="h-px flex-1 bg-line" />
              </div>
              <ol className="relative ml-[15px] space-y-1 border-l border-line">
                {g.events.map((e) => {
                  const ev = eventView(e.type)
                  const c = toneClasses(ev.tone)
                  const d = describeEvent(e)
                  return (
                    <li key={e.id} className="relative flex gap-4 rounded-xl py-2.5 pl-7 pr-3 transition-colors hover:bg-surface-2">
                      <span
                        className={cn(
                          'absolute -left-[15px] top-3 flex size-[30px] items-center justify-center rounded-full ring-4 ring-bg',
                          c.soft,
                        )}
                      >
                        <ev.icon className="size-3.5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-[13.5px] font-semibold text-ink">{d.title}</p>
                        {d.detail && <p className="mt-0.5 text-[12.5px] leading-snug text-muted">{d.detail}</p>}
                      </div>
                      <div className="shrink-0 text-right">
                        <span className="block text-[11.5px] tabular text-faint">{fmtTime(e.timestamp)}</span>
                        <Mono className="text-[10px]">{e.id}</Mono>
                      </div>
                    </li>
                  )
                })}
              </ol>
            </div>
          ))}
        </div>
      )}
    </PageContainer>
  )
}
