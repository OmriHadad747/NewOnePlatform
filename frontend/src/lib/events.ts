// Render an event as a human sentence for the timeline. The payload shape
// differs per type (outbound events nest the action under payload.payload);
// this normalizes them into { title, detail }.

import type { AipmEvent } from './types'
import { personLabel, titlecase } from './format'
import { AGENT_NAME } from './persona'

export interface EventDescription {
  title: string
  detail?: string
}

const inner = (e: AipmEvent) => (e.payload?.payload ?? {}) as Record<string, any>
const clip = (s: unknown, n = 160) => {
  const t = String(s ?? '').trim()
  return t.length > n ? t.slice(0, n).trimEnd() + '…' : t
}

function summarizeDeltas(deltas: any[]): string {
  if (!deltas?.length) return ''
  const first = deltas[0]
  const label = first.fields?.title || first.fields?.description || first.fields?.name || first.entity_id
  const more = deltas.length - 1
  return `${titlecase(first.op)} ${first.entity_type} “${clip(label, 48)}”${more > 0 ? ` +${more} more` : ''}`
}

export function describeEvent(e: AipmEvent): EventDescription {
  switch (e.type) {
    case 'project_initialized':
      return { title: `Project started: ${e.payload?.name ?? ''}`.trim() }
    case 'project_closed':
      return { title: 'Project closed', detail: e.payload?.reason ? clip(e.payload.reason) : undefined }
    case 'transcript_ingested':
      return { title: 'Transcript ingested', detail: clip(e.raw_text) }
    case 'manual_note':
      return { title: `Note from ${personLabel(e.source)}`, detail: clip(e.raw_text) }
    case 'message_received':
      return { title: `${personLabel(e.source)} replied`, detail: clip(e.raw_text) }
    case 'message_sent': {
      const p = inner(e)
      return { title: `${AGENT_NAME} messaged ${personLabel(p.to)}`, detail: clip(p.subject || p.body) }
    }
    case 'agent_proposal': {
      const kind = e.payload?.kind === 'model_revision' ? 'a model correction' : 'a change'
      return {
        title: `${AGENT_NAME} proposed ${kind}`,
        detail: summarizeDeltas(e.payload?.deltas ?? []) || clip(e.payload?.rationale),
      }
    }
    case 'human_approval': {
      const summary = summarizeDeltas(e.payload?.deltas ?? [])
      return {
        title: e.payload?.amended ? 'Recorded a partial outcome' : 'Approved',
        // A ticket-batch sign-off applies no deltas — say so rather than blank.
        detail: summary || `${AGENT_NAME} signed off; fanned out for confirmation`,
      }
    }
    case 'proposal_rejected':
      return { title: 'Proposal declined', detail: e.payload?.reason ? clip(e.payload.reason) : undefined }
    case 'ticket_opened': {
      const p = inner(e)
      return { title: 'Ticket opened', detail: clip(p.title || p.task_id) }
    }
    case 'flag_raised': {
      const p = inner(e)
      return { title: 'Flag raised', detail: clip(p.reason) }
    }
    case 'report_to_management': {
      const p = inner(e)
      return { title: 'Escalated to management', detail: clip(p.reason) }
    }
    default:
      return { title: titlecase(e.type) }
  }
}

// Group events into day buckets, newest first, each bucket newest-first.
export function groupByDay(events: AipmEvent[]): { day: string; label: string; events: AipmEvent[] }[] {
  const byDay = new Map<string, AipmEvent[]>()
  for (const e of events) {
    const day = String(e.timestamp ?? '').slice(0, 10) || 'unknown'
    if (!byDay.has(day)) byDay.set(day, [])
    byDay.get(day)!.push(e)
  }
  const today = new Date().toISOString().slice(0, 10)
  const yest = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10)
  return [...byDay.entries()]
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([day, evs]) => {
      let label = day
      if (day === today) label = 'Today'
      else if (day === yest) label = 'Yesterday'
      else if (day !== 'unknown') {
        const d = new Date(day + 'T00:00:00')
        if (!isNaN(d.getTime()))
          label = d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })
      }
      return { day, label, events: evs.slice().reverse() }
    })
}
