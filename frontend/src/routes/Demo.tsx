// Demo console — "god mode" for presenting the platform live. Initialize a
// project, feed Shlomi work (transcripts / notes / inbound messages) AS ANY
// actor, reply to its proposals as anyone, and watch state + the event stream
// react in real time beside you. Everything here drives the real backend.

import { AnimatePresence, motion } from 'framer-motion'
import {
  CheckCircle2,
  FileText,
  type LucideIcon,
  MessageCircle,
  Radio,
  Rocket,
  Send,
  Sparkles,
  StickyNote,
  Wand2,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { PageContainer, PageHeader } from '../components/PageHeader'
import { useToast } from '../components/Toast'
import { ProposalCard } from '../components/proposals/ProposalCard'
import {
  Avatar,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Mono,
  Tag,
} from '../components/ui'
import { cn } from '../lib/cn'
import { describeEvent } from '../lib/events'
import { eventView, fmtTime, personLabel, toneClasses } from '../lib/format'
import { projectStats } from '../lib/health'
import { interpretApprovals } from '../lib/approvals'
import { AGENT_NAME } from '../lib/persona'
import {
  useAddRawEvent,
  useEvents,
  useInitProject,
  useProject,
  useProjectState,
  useProposals,
} from '../lib/queries'
import type { CreateEventResponse, Proposal } from '../lib/types'

type FeedKind = 'transcript_ingested' | 'manual_note' | 'message_received'
const FEED_KINDS: { key: FeedKind; label: string; icon: LucideIcon }[] = [
  { key: 'transcript_ingested', label: 'Transcript', icon: FileText },
  { key: 'manual_note', label: 'Note', icon: StickyNote },
  { key: 'message_received', label: 'Message', icon: MessageCircle },
]

export function Demo() {
  const { data: project } = useProject()
  const hasProject = !!project?.name
  const actors = useActors()
  const [actor, setActor] = useState('')
  const currentActor = actor || project?.pm || actors[0] || 'pm@example.com'

  return (
    <PageContainer className="max-w-[1180px]">
      <PageHeader
        eyebrow="God mode"
        title="Demo console"
        subtitle={`Initialize a project, feed ${AGENT_NAME} work as anyone, and watch it react live. Everything here drives the real engine.`}
        actions={<ActorPicker actors={actors} value={currentActor} onChange={setActor} />}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-6">
          {!hasProject && <InitProject />}
          <FeedComposer actor={currentActor} />
          <PendingQueue actor={currentActor} />
        </div>
        <aside className="flex flex-col gap-6 lg:sticky lg:top-6 lg:self-start">
          <StateSnapshot />
          <LiveStream />
        </aside>
      </div>
    </PageContainer>
  )
}

// Team + PM/tech-lead, deduped. Memoized so the actor identity is stable.
function useActors(): string[] {
  const { data: project } = useProject()
  return useMemo(() => {
    const set = new Set<string>()
    ;(project?.team ?? []).forEach((m) => set.add(m))
    if (project?.pm) set.add(project.pm)
    if (project?.tech_lead) set.add(project.tech_lead)
    return [...set]
  }, [project])
}

function ActorPicker({
  actors,
  value,
  onChange,
}: {
  actors: string[]
  value: string
  onChange: (v: string) => void
}) {
  return (
    <label className="flex items-center gap-2.5 rounded-xl border border-line bg-surface py-1.5 pl-2.5 pr-3">
      <Avatar name={value} size="sm" />
      <span className="leading-tight">
        <span className="block text-[10px] font-semibold uppercase tracking-wide text-faint">Acting as</span>
        <input
          list="demo-actors"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label="Acting as"
          className="w-40 bg-transparent text-[13px] font-bold text-ink outline-none"
        />
      </span>
      <datalist id="demo-actors">
        {actors.map((a) => (
          <option key={a} value={a} />
        ))}
      </datalist>
    </label>
  )
}

function InitProject() {
  const init = useInitProject()
  const toast = useToast()
  const [form, setForm] = useState({
    name: '',
    description: '',
    team: '',
    start_date: '',
    end_date: '',
    pm: '',
  })
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async () => {
    if (!form.name.trim()) return
    try {
      await init.mutateAsync({
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        team: form.team ? form.team.split(',').map((s) => s.trim()).filter(Boolean) : undefined,
        start_date: form.start_date || undefined,
        end_date: form.end_date || undefined,
        pm: form.pm.trim() || undefined,
      })
      toast.success('Project created', `${AGENT_NAME} is ready. Feed it some work below.`)
    } catch {
      toast.error('Could not create project', 'The backend rejected it — check the fields and retry.')
    }
  }

  return (
    <Card>
      <CardHeader icon={Rocket} title="Start a project" />
      <div className="grid grid-cols-1 gap-3 px-5 pb-5 sm:grid-cols-2">
        <Field label="Project name" className="sm:col-span-2">
          <input className={inputCls} value={form.name} onChange={set('name')} placeholder="Score model replacement" />
        </Field>
        <Field label="Description" className="sm:col-span-2">
          <textarea className={inputCls} rows={2} value={form.description} onChange={set('description')} placeholder="What are we shipping?" />
        </Field>
        <Field label="Team (comma-separated)" className="sm:col-span-2">
          <input className={inputCls} value={form.team} onChange={set('team')} placeholder="alice, bob, carol" />
        </Field>
        <Field label="Start date">
          <input type="date" className={inputCls} value={form.start_date} onChange={set('start_date')} />
        </Field>
        <Field label="End date">
          <input type="date" className={inputCls} value={form.end_date} onChange={set('end_date')} />
        </Field>
        <Field label="Project manager (email)" className="sm:col-span-2">
          <input className={inputCls} value={form.pm} onChange={set('pm')} placeholder="pm@example.com" />
        </Field>
        <div className="sm:col-span-2">
          <Button variant="primary" icon={Rocket} loading={init.isPending} disabled={!form.name.trim()} onClick={submit}>
            Create project
          </Button>
        </div>
      </div>
    </Card>
  )
}

function FeedComposer({ actor }: { actor: string }) {
  const [kind, setKind] = useState<FeedKind>('transcript_ingested')
  const [text, setText] = useState('')
  const [result, setResult] = useState<CreateEventResponse | null>(null)
  const feed = useAddRawEvent()
  const toast = useToast()

  const submit = async () => {
    if (!text.trim()) return
    try {
      const res = await feed.mutateAsync({ type: kind, text: text.trim(), source: actor, channel: 'stub' })
      setResult(res)
      setText('')
    } catch {
      toast.error(`${AGENT_NAME} couldn't take that in`, 'The backend rejected the input. Try again.', {
        label: 'Retry',
        onClick: submit,
      })
    }
  }

  return (
    <Card>
      <CardHeader icon={Wand2} title={`Feed ${AGENT_NAME}`} action={<Mono>as {personLabel(actor)}</Mono>} />
      <div className="px-5 pb-5">
        <div className="mb-3 flex gap-1 rounded-xl border border-line bg-surface-2 p-1">
          {FEED_KINDS.map((k) => (
            <button
              key={k.key}
              onClick={() => setKind(k.key)}
              className={cn(
                'flex flex-1 items-center justify-center gap-1.5 rounded-lg py-1.5 text-[12.5px] font-semibold transition-colors',
                kind === k.key ? 'bg-surface text-accent shadow-card-sm' : 'text-ink-soft hover:text-ink',
              )}
            >
              <k.icon className="size-3.5" /> {k.label}
            </button>
          ))}
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          placeholder={
            kind === 'transcript_ingested'
              ? 'Paste a meeting transcript…'
              : kind === 'manual_note'
                ? 'Jot a note for Shlomi…'
                : 'An inbound message from this person…'
          }
          className={inputCls}
        />
        <div className="mt-3 flex items-center justify-between">
          <span className="text-[12px] text-muted">Shlomi will extract facts and propose changes.</span>
          <Button variant="primary" icon={Send} loading={feed.isPending} disabled={!text.trim()} onClick={submit}>
            Send
          </Button>
        </div>
        <AnimatePresence>{result && <FeedResult result={result} />}</AnimatePresence>
      </div>
    </Card>
  )
}

function FeedResult({ result }: { result: CreateEventResponse }) {
  const ex = result.extraction
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="mt-4 overflow-hidden"
    >
      <div className="rounded-xl border border-line bg-surface-2 p-3.5">
        <p className="mb-2 flex items-center gap-1.5 text-[12px] font-bold uppercase tracking-wide text-accent">
          <Sparkles className="size-3.5" /> {AGENT_NAME} reacted
        </p>
        {!ex && <p className="text-[13px] text-muted">Logged. No extraction ran.</p>}
        {ex?.skipped && <p className="text-[13px] text-muted">Skipped extraction: {ex.skipped}.</p>}
        {ex?.error && <p className="text-[13px] text-red">{ex.error}</p>}
        {ex?.proposal && (
          <p className="text-[13px] text-ink">
            Raised a proposal with {(ex.proposal.payload.deltas?.length ?? 0)} change(s) and{' '}
            {(ex.proposal.payload.actions?.length ?? 0)} action(s) — see the queue below.
          </p>
        )}
        {ex && !ex.proposal && !ex.skipped && !ex.error && (
          <p className="text-[13px] text-muted">Nothing needed changing.</p>
        )}
        {!!ex?.executed?.length && (
          <p className="mt-1 text-[12.5px] text-muted">Sent {ex.executed.length} message(s) automatically.</p>
        )}
        {!!ex?.conflicts?.length && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {ex.conflicts.map((c, i) => (
              <Tag key={i} tone="amber">
                {c.type.replace(/_/g, ' ')}
              </Tag>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  )
}

function PendingQueue({ actor }: { actor: string }) {
  const { data: proposals } = useProposals({ poll: true })
  const reply = useAddRawEvent()
  const toast = useToast()
  const [busyId, setBusyId] = useState<string | null>(null)
  const list = proposals ?? []

  const send = async (p: Proposal, text: string) => {
    setBusyId(p.id)
    try {
      const res = await reply.mutateAsync({
        type: 'message_received',
        text,
        source: actor,
        channel: 'stub',
        thread_id: p.payload.thread_id,
      })
      const o = interpretApprovals(res.approvals)
      toast[o.kind](o.title, o.description)
    } catch {
      toast.error(`${AGENT_NAME} didn't respond`, 'Reply could not be delivered.', {
        label: 'Retry',
        onClick: () => send(p, text),
      })
    } finally {
      setBusyId(null)
    }
  }

  return (
    <Card>
      <CardHeader icon={CheckCircle2} title="Pending — reply as anyone" count={list.length || undefined} />
      <div className="px-5 pb-5">
        {list.length === 0 ? (
          <p className="py-4 text-center text-[13px] text-muted">Nothing pending. Feed Shlomi something above.</p>
        ) : (
          <div className="flex flex-col gap-4">
            <AnimatePresence mode="popLayout">
              {list.map((p) => (
                <ProposalCard key={p.id} proposal={p} busy={busyId === p.id} onSend={(t) => send(p, t)} />
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>
    </Card>
  )
}

function StateSnapshot() {
  const { data: state } = useProjectState({ poll: true })
  const s = projectStats(state)
  const cells = [
    { label: 'Tasks', value: s.tasksTotal, tone: 'accent' as const },
    { label: 'Blocked', value: s.tasksBlocked, tone: 'red' as const },
    { label: 'Risks', value: s.risksOpen, tone: 'amber' as const },
    { label: 'Questions', value: s.openQuestions, tone: 'violet' as const },
  ]
  return (
    <Card>
      <CardHeader title="Live state" count={<Tag tone={s.health.tone} dot>{s.health.label}</Tag>} />
      <div className="grid grid-cols-2 gap-2.5 px-5 pb-5">
        {cells.map((c) => (
          <div key={c.label} className="rounded-xl border border-line-2 bg-surface-2/50 px-3 py-2.5">
            <p className={cn('text-[20px] font-extrabold tabular', toneClasses(c.tone).text)}>{c.value}</p>
            <p className="text-[11px] font-medium text-muted">{c.label}</p>
          </div>
        ))}
      </div>
    </Card>
  )
}

function LiveStream() {
  const { data: events } = useEvents({ poll: true })
  const recent = useMemo(() => (events ?? []).slice().reverse().slice(0, 10), [events])
  return (
    <Card className="flex flex-col">
      <CardHeader icon={Radio} title="Event stream" action={<span className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-green"><span className="size-1.5 animate-pulse rounded-full bg-green" /> Live</span>} />
      <div className="max-h-[420px] overflow-y-auto px-3 pb-3">
        {recent.length === 0 ? (
          <EmptyState icon={Radio} title="Quiet for now" description="Events appear here the moment they happen." />
        ) : (
          <AnimatePresence initial={false}>
            {recent.map((e) => {
              const ev = eventView(e.type)
              const c = toneClasses(ev.tone)
              const d = describeEvent(e)
              return (
                <motion.div
                  key={e.id}
                  layout
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="flex items-start gap-2.5 rounded-xl px-2 py-2"
                >
                  <span className={cn('mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-lg', c.soft)}>
                    <ev.icon className="size-3" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12.5px] font-semibold text-ink">{d.title}</p>
                    {d.detail && <p className="truncate text-[11.5px] text-muted">{d.detail}</p>}
                  </div>
                  <span className="shrink-0 text-[10.5px] tabular text-faint">{fmtTime(e.timestamp)}</span>
                </motion.div>
              )
            })}
          </AnimatePresence>
        )}
      </div>
    </Card>
  )
}

const inputCls =
  'w-full resize-none rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[13.5px] text-ink outline-none transition-colors placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/30'

function Field({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={cn('flex flex-col gap-1.5', className)}>
      <span className="text-[12px] font-semibold text-ink-soft">{label}</span>
      {children}
    </label>
  )
}
