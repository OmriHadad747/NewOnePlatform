// Turn a proposal's raw deltas/actions into readable, consistently-styled view
// models. The backend summarizes proposals as terse strings; here we render
// them richly (icon + tone + human label + the notable field changes) so a
// manager can decide at a glance. Field vocabulary mirrors ai-engine/schema.

import {
  ArrowUpRight,
  Flag,
  MinusCircle,
  PencilLine,
  PlusCircle,
  Send,
  Ticket,
  type LucideIcon,
} from 'lucide-react'
import type { Action, Proposal, ProposalDelta } from './types'
import { fmtDate, personLabel, severity, taskStatus, titlecase, type Tone } from './format'

const entityLabel = (fields: Record<string, any> | undefined, id: string) =>
  fields?.title || fields?.description || fields?.name || titlecase(id)

export interface FieldChange {
  label: string
  value: string
  tone?: Tone
}

function notableChanges(d: ProposalDelta): FieldChange[] {
  const f = d.fields ?? {}
  const out: FieldChange[] = []
  if (f.status != null) {
    const sv = d.entity_type === 'OpenQuestion' ? null : taskStatus(f.status)
    out.push({ label: 'Status', value: sv?.label ?? titlecase(f.status), tone: sv?.tone })
  }
  if (f.severity != null) {
    const sv = severity(f.severity)
    out.push({ label: 'Severity', value: sv.label, tone: sv.tone })
  }
  if (f.owner != null || f.assignee != null)
    out.push({ label: 'Owner', value: personLabel(f.owner ?? f.assignee) })
  if (f.due_date != null) out.push({ label: 'Due', value: fmtDate(f.due_date) })
  return out
}

const OP_META: Record<ProposalDelta['op'], { icon: LucideIcon; tone: Tone; verb: string }> = {
  create: { icon: PlusCircle, tone: 'green', verb: 'Add' },
  update: { icon: PencilLine, tone: 'blue', verb: 'Update' },
  delete: { icon: MinusCircle, tone: 'red', verb: 'Remove' },
}

export interface DeltaView {
  icon: LucideIcon
  tone: Tone
  verb: string
  entityType: string
  label: string
  changes: FieldChange[]
  sourceSpan?: string
}

export function describeDelta(d: ProposalDelta): DeltaView {
  const meta = OP_META[d.op] ?? OP_META.update
  return {
    icon: meta.icon,
    tone: meta.tone,
    verb: meta.verb,
    entityType: d.entity_type,
    label: entityLabel(d.fields, d.entity_id),
    changes: notableChanges(d),
    sourceSpan: (d as any).source_span ?? undefined,
  }
}

const ACTION_META: Record<string, { icon: LucideIcon; tone: Tone; verb: string }> = {
  open_ticket: { icon: Ticket, tone: 'teal', verb: 'Open ticket' },
  raise_flag: { icon: Flag, tone: 'amber', verb: 'Raise flag' },
  escalate_to_management: { icon: ArrowUpRight, tone: 'red', verb: 'Escalate' },
  send_message: { icon: Send, tone: 'blue', verb: 'Send message' },
}

export interface ActionView {
  icon: LucideIcon
  tone: Tone
  verb: string
  label: string
  detail?: string
}

export function describeAction(a: Action): ActionView {
  const meta = ACTION_META[a.type] ?? { icon: Send, tone: 'muted' as Tone, verb: titlecase(a.type) }
  const p = a.payload ?? {}
  return {
    icon: meta.icon,
    tone: meta.tone,
    verb: meta.verb,
    label: p.title || p.subject || titlecase(p.entity_id || p.task_id || a.type),
    detail: p.reason || p.body || undefined,
  }
}

export interface ProposalKind {
  label: string
  tone: Tone
}

// A short headline classifying the proposal, shown as a tag.
export function proposalKind(p: Proposal): ProposalKind {
  const payload = p.payload
  if (payload.kind === 'model_revision') return { label: 'Model correction', tone: 'violet' }
  const actions = payload.actions ?? []
  if (actions.some((a) => a.payload?.requires_owner_confirmation))
    return { label: 'Ticket batch', tone: 'teal' }
  if (actions.some((a) => a.type === 'raise_flag' || a.type === 'escalate_to_management'))
    return { label: 'Needs sign-off', tone: 'amber' }
  if (actions.some((a) => a.type === 'open_ticket')) return { label: 'Open ticket', tone: 'teal' }
  return { label: 'Proposed change', tone: 'accent' }
}

export interface ProposalView {
  kind: ProposalKind
  deltas: DeltaView[]
  actions: ActionView[]
  rationale?: string
  threadId?: string
  approver?: string
  empty: boolean
}

export function describeProposal(p: Proposal): ProposalView {
  const deltas = (p.payload.deltas ?? []).map(describeDelta)
  const actions = (p.payload.actions ?? []).map(describeAction)
  return {
    kind: proposalKind(p),
    deltas,
    actions,
    rationale: p.payload.rationale,
    threadId: p.payload.thread_id,
    approver: p.payload.approver,
    empty: deltas.length === 0 && actions.length === 0,
  }
}

// Who the agent asked to sign off — the reply must come from them for the
// resolver to map it back. Mirrors backend _approval_recipient: explicit
// approver, else PM, else tech lead, else first team member.
export function approverFor(p: Proposal, meta?: { pm?: string; tech_lead?: string; team?: string[] }): string {
  return (
    p.payload.approver ||
    meta?.pm ||
    meta?.tech_lead ||
    (meta?.team && meta.team[0]) ||
    'pm@project'
  )
}
