// Reconstruct conversations from the event log. A thread is the sequence of
// message_sent (from Shlomi) and message_received (from a person) events that
// share a thread_id — mirroring backend _thread_history, but richer (subjects,
// timestamps, participants) for a chat-style UI.

import type { AipmEvent, Proposal } from './types'
import { personLabel } from './format'

export interface ThreadMessage {
  sender: 'agent' | string
  isAgent: boolean
  text: string
  subject?: string
  timestamp: string
}

export interface Thread {
  id: string
  subject: string
  messages: ThreadMessage[]
  participants: string[] // non-agent people, by raw identifier
  lastTimestamp: string
  open: boolean // has a still-pending proposal on this thread
}

export function reconstructThreads(events: AipmEvent[], proposals: Proposal[] = []): Thread[] {
  const byThread = new Map<string, ThreadMessage[]>()
  const subjects = new Map<string, string>()
  const people = new Map<string, Set<string>>()

  const ensure = (id: string) => {
    if (!byThread.has(id)) {
      byThread.set(id, [])
      people.set(id, new Set())
    }
  }

  for (const e of events) {
    if (e.type === 'message_sent') {
      const p = (e.payload?.payload ?? {}) as Record<string, any>
      const id = p.thread_id
      if (!id) continue
      ensure(id)
      byThread.get(id)!.push({
        sender: 'agent',
        isAgent: true,
        text: String(p.body ?? ''),
        subject: p.subject,
        timestamp: e.timestamp,
      })
      if (p.subject && !subjects.has(id)) subjects.set(id, String(p.subject))
      if (p.to) people.get(id)!.add(String(p.to))
    } else if (e.type === 'message_received') {
      const id = e.payload?.thread_id
      if (!id || !e.raw_text) continue
      ensure(id)
      byThread.get(id)!.push({
        sender: e.source,
        isAgent: false,
        text: e.raw_text,
        timestamp: e.timestamp,
      })
      people.get(id)!.add(e.source)
    }
  }

  const openThreads = new Set(
    proposals.map((p) => p.payload.thread_id).filter((x): x is string => !!x),
  )

  return [...byThread.entries()]
    .map(([id, messages]) => {
      messages.sort((a, b) => (a.timestamp < b.timestamp ? -1 : 1))
      const last = messages[messages.length - 1]
      return {
        id,
        subject: subjects.get(id) || (messages[0]?.text ?? '').slice(0, 60) || 'Conversation',
        messages,
        participants: [...(people.get(id) ?? [])],
        lastTimestamp: last?.timestamp ?? '',
        open: openThreads.has(id),
      }
    })
    .filter((t) => t.messages.length > 0)
    .sort((a, b) => (a.lastTimestamp < b.lastTimestamp ? 1 : -1))
}

export const threadTitle = (t: Thread) =>
  t.subject.replace(/^(Re:|Approval needed:|Quick check before I record this:)\s*/i, '').trim() ||
  t.participants.map(personLabel).join(', ') ||
  'Conversation'
