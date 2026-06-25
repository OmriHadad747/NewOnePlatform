// Executive overview: project health at a glance + "Ask Shlomi" — a
// free-language Q&A answered from real project state via POST /ask. The chat is
// resilient: live model, with a friendly error + one-tap retry when it hiccups
// (the brief's "live model, be forgiving on retries").

import { motion } from 'framer-motion'
import { ArrowUp, RotateCcw, Sparkles } from 'lucide-react'
import { useRef, useState } from 'react'
import { ProjectPulse } from '../components/ProjectPulse'
import { PageContainer, PageHeader } from '../components/PageHeader'
import { Avatar, Card, CardHeader } from '../components/ui'
import { cn } from '../lib/cn'
import { projectStats } from '../lib/health'
import { toneClasses } from '../lib/format'
import { AGENT_NAME } from '../lib/persona'
import { useAsk, useProject, useProjectState } from '../lib/queries'

interface ChatTurn {
  id: number
  question: string
  answer?: string
  failed?: boolean
}

const SUGGESTIONS = [
  'What are the biggest blockers right now?',
  'Are we on track for the deadline?',
  'Which risks need attention?',
  'Who owns the BigQuery work?',
]

export function Exec() {
  const { data: project } = useProject()
  const { data: state } = useProjectState({ poll: true })
  const stats = projectStats(state)
  const c = toneClasses(stats.health.tone)

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Executive"
        title={project?.name ? `${project.name} — at a glance` : 'Overview'}
        subtitle={`Project health, and a direct line to ${AGENT_NAME}. Ask anything in plain language.`}
      />

      <div className={cn('mb-6 flex flex-wrap items-center gap-x-8 gap-y-4 rounded-2xl border p-5', c.soft)}>
        <div className="flex items-center gap-3">
          <span className={cn('flex size-11 items-center justify-center rounded-2xl bg-surface', toneClasses(stats.health.tone).text)}>
            <Sparkles className="size-6" />
          </span>
          <div>
            <p className="text-[12px] font-bold uppercase tracking-wide opacity-70">Status</p>
            <p className="text-[20px] font-extrabold leading-tight">{stats.health.label}</p>
          </div>
        </div>
        <HeroStat label="Tasks done" value={`${stats.tasksDone}/${stats.tasksTotal}`} />
        <HeroStat label="Blocked" value={stats.tasksBlocked} />
        <HeroStat label="Open risks" value={`${stats.risksOpen}${stats.risksHigh ? ` · ${stats.risksHigh} high` : ''}`} />
        <HeroStat label="Open questions" value={stats.openQuestions} />
        {project?.end_date && <HeroStat label="Target" value={new Date(project.end_date + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })} />}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <AskShlomi />
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <ProjectPulse />
        </aside>
      </div>
    </PageContainer>
  )
}

function HeroStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <p className="text-[12px] font-bold uppercase tracking-wide opacity-70">{label}</p>
      <p className="text-[20px] font-extrabold leading-tight tabular">{value}</p>
    </div>
  )
}

function AskShlomi() {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [input, setInput] = useState('')
  const ask = useAsk()
  const seq = useRef(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const scrollToEnd = () =>
    requestAnimationFrame(() => {
      const el = scrollRef.current
      if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    })

  const submit = async (question: string) => {
    const q = question.trim()
    if (!q || ask.isPending) return
    const id = ++seq.current
    setTurns((t) => [...t, { id, question }])
    setInput('')
    scrollToEnd()
    try {
      const res = await ask.mutateAsync(q)
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, answer: res.answer } : x)))
    } catch {
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, failed: true } : x)))
    } finally {
      scrollToEnd()
    }
  }

  const retry = (turn: ChatTurn) => {
    setTurns((t) => t.filter((x) => x.id !== turn.id))
    submit(turn.question)
  }

  return (
    <Card className="flex h-[560px] flex-col">
      <CardHeader icon={Sparkles} title={`Ask ${AGENT_NAME}`} />
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-5">
        {turns.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <span className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-accent-soft text-accent">
              <Sparkles className="size-7" />
            </span>
            <p className="text-[15px] font-bold text-ink">Ask about the project</p>
            <p className="mt-1 max-w-xs text-[13px] text-muted">
              {AGENT_NAME} answers from the live project state — blockers, risks, owners, timeline.
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => submit(s)}
                  className="rounded-full border border-line bg-surface px-3 py-1.5 text-[12.5px] font-medium text-ink-soft transition-colors hover:border-accent hover:text-accent"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-5 py-2">
            {turns.map((t) => (
              <Turn key={t.id} turn={t} onRetry={() => retry(t)} />
            ))}
            {ask.isPending && <Thinking />}
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          submit(input)
        }}
        className="border-t border-line p-3"
      >
        <div className="flex items-end gap-2 rounded-2xl border border-line bg-surface-2 p-1.5 focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/30">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit(input)
              }
            }}
            rows={1}
            placeholder={`Ask ${AGENT_NAME} anything…`}
            className="max-h-32 min-h-9 flex-1 resize-none bg-transparent px-2.5 py-2 text-[14px] text-ink outline-none placeholder:text-faint"
          />
          <button
            type="submit"
            disabled={!input.trim() || ask.isPending}
            aria-label="Send"
            className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-accent text-accent-ink transition-all hover:bg-accent-hover disabled:opacity-40"
          >
            <ArrowUp className="size-[18px]" />
          </button>
        </div>
      </form>
    </Card>
  )
}

function Turn({ turn, onRetry }: { turn: ChatTurn; onRetry: () => void }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-row-reverse gap-2.5">
        <Avatar name="you" size="md" />
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-accent px-3.5 py-2.5 text-[13.5px] leading-relaxed text-accent-ink">
          {turn.question}
        </div>
      </div>
      {(turn.answer || turn.failed) && (
        <div className="flex gap-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
            <Sparkles className="size-4" />
          </span>
          {turn.failed ? (
            <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-red-soft px-3.5 py-2.5">
              <p className="text-[13.5px] font-semibold text-red">{AGENT_NAME} didn’t respond</p>
              <p className="mt-0.5 text-[12.5px] text-ink-soft">The model couldn’t be reached just now.</p>
              <button onClick={onRetry} className="mt-2 inline-flex items-center gap-1.5 text-[12.5px] font-bold text-accent hover:underline">
                <RotateCcw className="size-3.5" /> Try again
              </button>
            </div>
          ) : (
            <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tl-sm bg-surface-2 px-3.5 py-2.5 text-[13.5px] leading-relaxed text-ink">
              {turn.answer}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Thinking() {
  return (
    <div className="flex gap-2.5">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
        <Sparkles className="size-4 animate-pulse" />
      </span>
      <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm bg-surface-2 px-4 py-3">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="size-1.5 rounded-full bg-faint"
            animate={{ opacity: [0.3, 1, 0.3] }}
            transition={{ duration: 1, repeat: Infinity, delay: i * 0.18 }}
          />
        ))}
      </div>
    </div>
  )
}
