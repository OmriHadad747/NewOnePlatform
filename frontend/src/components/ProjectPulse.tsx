// A compact, glanceable read of project health: the status, a progress bar,
// the few counts that matter, and the most recent activity. Shared by the
// manager cockpit and the exec overview so "health" reads identically in both.

import { AlertTriangle, CircleDot, HelpCircle, ListTodo } from 'lucide-react'
import { eventView, fmtTime, type Tone } from '../lib/format'
import { projectStats } from '../lib/health'
import { useEvents, useProjectState } from '../lib/queries'
import { toneClasses } from '../lib/format'
import { Card, CardHeader, Skeleton, Tag } from './ui'

function Stat({ icon: Icon, tone, label, value }: { icon: typeof ListTodo; tone: Tone; label: string; value: number }) {
  const c = toneClasses(tone)
  return (
    <div className="flex items-center gap-2.5 rounded-xl border border-line-2 bg-surface-2/50 px-3 py-2.5">
      <span className={`flex size-7 items-center justify-center rounded-lg ${c.soft}`}>
        <Icon className="size-4" />
      </span>
      <div className="leading-tight">
        <p className="text-[17px] font-extrabold tabular text-ink">{value}</p>
        <p className="text-[11px] font-medium text-muted">{label}</p>
      </div>
    </div>
  )
}

export function ProjectPulse() {
  const { data: state, isLoading } = useProjectState({ poll: true })
  const { data: events } = useEvents({ poll: true })
  const stats = projectStats(state)
  const pct = stats.tasksTotal ? Math.round((stats.tasksDone / stats.tasksTotal) * 100) : 0
  const recent = (events ?? []).slice().reverse().slice(0, 6)

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardHeader title="Project pulse" count={<Tag tone={stats.health.tone} dot>{stats.health.label}</Tag>} />
        <div className="px-5 pb-5">
          {isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : (
            <>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-[12px] font-medium text-muted">Tasks complete</span>
                <span className="text-[12px] font-bold text-ink">
                  {stats.tasksDone}/{stats.tasksTotal} · {pct}%
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-surface-3">
                <div className="h-full rounded-full bg-green transition-all duration-500" style={{ width: `${pct}%` }} />
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2.5">
                <Stat icon={CircleDot} tone="blue" label="In progress" value={stats.tasksInProgress} />
                <Stat icon={AlertTriangle} tone="red" label="Blocked" value={stats.tasksBlocked} />
                <Stat icon={AlertTriangle} tone="amber" label="Open risks" value={stats.risksOpen} />
                <Stat icon={HelpCircle} tone="violet" label="Open questions" value={stats.openQuestions} />
              </div>
            </>
          )}
        </div>
      </Card>

      <Card>
        <CardHeader title="Recent activity" />
        <div className="px-3 pb-3">
          {recent.length === 0 ? (
            <p className="px-2 py-6 text-center text-[13px] text-muted">Nothing yet.</p>
          ) : (
            recent.map((e) => {
              const ev = eventView(e.type)
              const c = toneClasses(ev.tone)
              return (
                <div key={e.id} className="flex items-center gap-3 rounded-xl px-2 py-2">
                  <span className={`flex size-7 shrink-0 items-center justify-center rounded-lg ${c.soft}`}>
                    <ev.icon className="size-3.5" />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink-soft">{ev.label}</span>
                  <span className="shrink-0 text-[11px] tabular text-faint">{fmtTime(e.timestamp)}</span>
                </div>
              )
            })
          )}
        </div>
      </Card>
    </div>
  )
}
