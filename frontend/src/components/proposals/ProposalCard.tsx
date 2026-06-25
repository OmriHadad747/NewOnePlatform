// One pending proposal, rendered for a human decision. Approval in this system
// is a reply on the proposal's thread (there is no approve endpoint), so the
// quick actions send a short reply and the "Reply" composer sends a nuanced
// one — both flow through the same engine path.

import { motion } from 'framer-motion'
import { Check, CornerUpLeft, Sparkles, X } from 'lucide-react'
import { useState } from 'react'
import { AGENT_NAME } from '../../lib/persona'
import { toneClasses, type Tone } from '../../lib/format'
import { describeProposal } from '../../lib/proposal'
import type { Proposal } from '../../lib/types'
import { Modal } from '../Modal'
import { Button, Mono, Tag } from '../ui'

const APPROVE_TEXT = 'Yes, please go ahead.'
const DECLINE_TEXT = "No — let's not do that for now."

export function ProposalCard({
  proposal,
  onSend,
  busy,
}: {
  proposal: Proposal
  onSend: (text: string) => Promise<void>
  busy: boolean
}) {
  const v = describeProposal(proposal)
  const [composer, setComposer] = useState(false)
  const [draft, setDraft] = useState('')

  const sendComposer = async () => {
    const text = draft.trim()
    if (!text) return
    await onSend(text)
    setDraft('')
    setComposer(false)
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98 }}
      className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card-sm"
    >
      <div className="flex items-start gap-3.5 p-5">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
          <Sparkles className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[14px] font-bold text-ink">{AGENT_NAME} proposes</p>
            <Tag tone={v.kind.tone}>{v.kind.label}</Tag>
          </div>

          {v.rationale && (
            <p className="mt-1.5 rounded-xl bg-violet-soft px-3 py-2 text-[12.5px] leading-relaxed text-ink-soft">
              {v.rationale}
            </p>
          )}

          <div className="mt-3 flex flex-col gap-2">
            {v.deltas.map((d, i) => (
              <ChangeRow key={`d${i}`} icon={d.icon} tone={d.tone} title={`${d.verb} ${d.entityType.toLowerCase()} · ${d.label}`}>
                {d.changes.map((c, j) => (
                  <span key={j} className="inline-flex items-center gap-1 text-[12px] text-muted">
                    {c.label}:&nbsp;
                    <span className={c.tone ? toneClasses(c.tone).text + ' font-semibold' : 'font-semibold text-ink-soft'}>
                      {c.value}
                    </span>
                  </span>
                ))}
              </ChangeRow>
            ))}
            {v.actions.map((a, i) => (
              <ChangeRow key={`a${i}`} icon={a.icon} tone={a.tone} title={`${a.verb} · ${a.label}`}>
                {a.detail && <span className="text-[12px] leading-snug text-muted">{a.detail}</span>}
              </ChangeRow>
            ))}
            {v.empty && <p className="text-[13px] text-muted">A bookkeeping change with no visible fields.</p>}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button size="sm" variant="primary" icon={Check} loading={busy} onClick={() => onSend(APPROVE_TEXT)}>
              Approve
            </Button>
            <Button size="sm" variant="secondary" icon={CornerUpLeft} disabled={busy} onClick={() => setComposer(true)}>
              Reply
            </Button>
            <Button size="sm" variant="ghost" icon={X} disabled={busy} onClick={() => onSend(DECLINE_TEXT)}>
              Decline
            </Button>
            {v.threadId && <Mono className="ml-auto">{v.threadId}</Mono>}
          </div>
        </div>
      </div>

      <Modal
        open={composer}
        onClose={() => setComposer(false)}
        title={`Reply to ${AGENT_NAME}`}
        description="Approve, decline, or steer it — in your own words. Shlomi reads your reply and acts."
        footer={
          <>
            <Button variant="ghost" onClick={() => setComposer(false)}>
              Cancel
            </Button>
            <Button variant="primary" loading={busy} disabled={!draft.trim()} onClick={sendComposer}>
              Send reply
            </Button>
          </>
        }
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={4}
          autoFocus
          placeholder={'e.g. "Yes, but keep the dependency open" · "Record it anyway" · "Actually that dependency isn\'t real"'}
          className="w-full resize-none rounded-xl border border-line bg-surface-2 px-3.5 py-3 text-[14px] text-ink outline-none transition-colors placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/30"
        />
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {['Yes, go ahead', 'Record it anyway', 'Decline for now'].map((q) => (
            <button
              key={q}
              onClick={() => setDraft(q)}
              className="rounded-full border border-line bg-surface px-3 py-1 text-[12px] font-medium text-ink-soft transition-colors hover:bg-surface-2"
            >
              {q}
            </button>
          ))}
        </div>
      </Modal>
    </motion.div>
  )
}

function ChangeRow({
  icon: Icon,
  tone,
  title,
  children,
}: {
  icon: typeof Check
  tone: Tone
  title: string
  children?: React.ReactNode
}) {
  const c = toneClasses(tone)
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-line-2 bg-surface-2/60 px-3 py-2">
      <span className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-lg ${c.soft}`}>
        <Icon className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold text-ink">{title}</p>
        {children && <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5">{children}</div>}
      </div>
    </div>
  )
}
