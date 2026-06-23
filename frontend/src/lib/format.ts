// Shared presentation helpers. This is the single source of truth for how a
// raw status/severity/event-type maps to a label + color token, so every
// screen renders the same fact the same way (the consistency the design asks
// for). Status vocabulary is LLM-chosen, so matching is lenient — mirroring
// ai-engine/review.py's tolerant sets.

import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  FileText,
  Flag,
  MessageCircle,
  MessageSquare,
  Send,
  Sparkles,
  Ticket,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import type { EventType } from './types'

export type Tone = 'accent' | 'teal' | 'green' | 'red' | 'amber' | 'blue' | 'violet' | 'muted'

const TONE_CLASS: Record<Tone, { text: string; soft: string; dot: string }> = {
  accent: { text: 'text-accent', soft: 'bg-accent-soft text-accent', dot: 'bg-accent' },
  teal: { text: 'text-teal', soft: 'bg-teal-soft text-teal', dot: 'bg-teal' },
  green: { text: 'text-green', soft: 'bg-green-soft text-green', dot: 'bg-green' },
  red: { text: 'text-red', soft: 'bg-red-soft text-red', dot: 'bg-red' },
  amber: { text: 'text-amber', soft: 'bg-amber-soft text-amber', dot: 'bg-amber' },
  blue: { text: 'text-blue', soft: 'bg-blue-soft text-blue', dot: 'bg-blue' },
  violet: { text: 'text-violet', soft: 'bg-violet-soft text-violet', dot: 'bg-violet' },
  muted: { text: 'text-muted', soft: 'bg-surface-3 text-ink-soft', dot: 'bg-faint' },
}
export const toneClasses = (t: Tone) => TONE_CLASS[t]

const norm = (s: unknown) => String(s ?? '').toLowerCase().replace(/[\s-]+/g, '_')

const DONE = new Set(['done', 'complete', 'completed', 'finished', 'closed', 'resolved'])
const PROG = new Set(['in_progress', 'active', 'started', 'ongoing', 'doing'])
const BLOCK = new Set(['blocked', 'stuck', 'at_risk', 'waiting'])

export interface StatusView {
  label: string
  tone: Tone
}

export function taskStatus(raw: unknown): StatusView {
  const s = norm(raw)
  if (!s) return { label: 'No status', tone: 'muted' }
  if (DONE.has(s)) return { label: 'Done', tone: 'green' }
  if (BLOCK.has(s)) return { label: titlecase(raw), tone: 'red' }
  if (PROG.has(s)) return { label: 'In progress', tone: 'blue' }
  if (s === 'not_started' || s === 'todo' || s === 'planned' || s === 'new')
    return { label: 'Not started', tone: 'muted' }
  return { label: titlecase(raw), tone: 'accent' }
}

export function severity(raw: unknown): StatusView {
  const s = norm(raw)
  if (s === 'critical') return { label: 'Critical', tone: 'red' }
  if (s === 'high') return { label: 'High', tone: 'red' }
  if (s === 'medium' || s === 'med' || s === 'moderate') return { label: 'Medium', tone: 'amber' }
  if (s === 'low') return { label: 'Low', tone: 'teal' }
  if (!s) return { label: 'Unrated', tone: 'muted' }
  return { label: titlecase(raw), tone: 'amber' }
}

export function questionStatus(raw: unknown): StatusView {
  const s = norm(raw)
  if (['resolved', 'closed', 'answered', 'decided', 'done'].includes(s))
    return { label: titlecase(raw), tone: 'green' }
  return { label: raw ? titlecase(raw) : 'Open', tone: 'amber' }
}

export interface EventView {
  icon: LucideIcon
  tone: Tone
  label: string
}

export function eventView(type: EventType): EventView {
  switch (type) {
    case 'agent_proposal':
      return { icon: Sparkles, tone: 'accent', label: 'Proposal' }
    case 'human_approval':
      return { icon: CheckCircle2, tone: 'green', label: 'Approved' }
    case 'proposal_rejected':
      return { icon: XCircle, tone: 'red', label: 'Declined' }
    case 'message_received':
      return { icon: MessageCircle, tone: 'blue', label: 'Message in' }
    case 'message_sent':
      return { icon: Send, tone: 'teal', label: 'Message sent' }
    case 'transcript_ingested':
      return { icon: FileText, tone: 'violet', label: 'Transcript' }
    case 'manual_note':
      return { icon: MessageSquare, tone: 'muted', label: 'Note' }
    case 'ticket_opened':
      return { icon: Ticket, tone: 'teal', label: 'Ticket opened' }
    case 'flag_raised':
      return { icon: Flag, tone: 'amber', label: 'Flag raised' }
    case 'report_to_management':
      return { icon: ArrowUpRight, tone: 'red', label: 'Escalated' }
    case 'project_initialized':
      return { icon: Sparkles, tone: 'accent', label: 'Project started' }
    case 'project_closed':
      return { icon: XCircle, tone: 'muted', label: 'Project closed' }
    default:
      return { icon: AlertTriangle, tone: 'muted', label: type }
  }
}

export function titlecase(s: unknown): string {
  return String(s ?? '')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim()
}

// A person identifier may be an email or a free-text name; derive a short,
// stable label + initials + a deterministic avatar tone from it.
export function personLabel(raw: unknown): string {
  const s = String(raw ?? '').trim()
  if (!s) return 'Unassigned'
  const at = s.indexOf('@')
  return at > 0 ? s.slice(0, at) : s
}

export function initials(raw: unknown): string {
  const label = personLabel(raw)
  if (label === 'Unassigned') return '?'
  const parts = label.split(/[.\s_-]+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return label.slice(0, 2).toUpperCase()
}

const AVATAR_TONES: Tone[] = ['accent', 'teal', 'blue', 'violet', 'green', 'amber']
export function avatarTone(raw: unknown): Tone {
  const s = personLabel(raw)
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return AVATAR_TONES[h % AVATAR_TONES.length]
}

// --- dates ---------------------------------------------------------------

export function fmtDate(iso: unknown): string {
  const s = String(iso ?? '')
  if (!s) return ''
  const d = new Date(s.length <= 10 ? s + 'T00:00:00' : s)
  if (isNaN(d.getTime())) return s
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function fmtTime(iso: unknown): string {
  const d = new Date(String(iso ?? ''))
  if (isNaN(d.getTime())) return ''
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  return sameDay
    ? d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function relativeDue(due: unknown): { label: string; soon: boolean; overdue: boolean } {
  const s = String(due ?? '')
  if (!s) return { label: '', soon: false, overdue: false }
  const d = new Date(s.length <= 10 ? s + 'T00:00:00' : s)
  if (isNaN(d.getTime())) return { label: s, soon: false, overdue: false }
  const days = Math.ceil((d.getTime() - Date.now()) / 86_400_000)
  return { label: fmtDate(s), soon: days >= 0 && days <= 14, overdue: days < 0 }
}
