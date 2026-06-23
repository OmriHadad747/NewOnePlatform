// Thin typed HTTP client for the backend. Mirrors cli/'s role: rendering layer
// only, no business logic. Every model-dependent call can fail (network/LLM),
// so errors are surfaced as a typed ApiError the UI can show *nicely* and the
// query layer retries with backoff.

import type {
  AipmEvent,
  AskResponse,
  CreateEventResponse,
  ProjectInput,
  ProjectMeta,
  ProjectStateResponse,
  Proposal,
} from './types'

const BASE = '/api'

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail || `Request failed (${status})`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE + path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    })
  } catch {
    // Network-level failure (backend down, DNS, offline). Distinct status so
    // the UI can show a "can't reach the agent" state vs. a server error.
    throw new ApiError(0, 'Could not reach the backend. Is it running?')
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      detail = body?.detail ? String(body.detail) : detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const isoNow = () => new Date().toISOString()
const rid = (p: string) => `${p}_${Math.random().toString(16).slice(2, 14)}`

export const api = {
  getProject: () => request<ProjectMeta>('/project'),
  getState: () => request<ProjectStateResponse>('/state'),
  getEvents: () => request<AipmEvent[]>('/events'),
  getProposals: () => request<Proposal[]>('/proposals'),

  initProject: (body: ProjectInput) =>
    request<AipmEvent>('/project', { method: 'POST', body: JSON.stringify(body) }),

  closeProject: (reason?: string) =>
    request<{ closed: boolean; event_id: string }>('/project/close', {
      method: 'POST',
      body: JSON.stringify({ reason: reason ?? '' }),
    }),

  // Raw-input events. The backend auto-extracts and (for replies) resolves
  // approvals in the same request — the response carries it all back.
  addRawEvent: (params: {
    type: 'transcript_ingested' | 'manual_note' | 'message_received'
    text: string
    source: string
    channel?: string
    thread_id?: string
  }) => {
    const payload: Record<string, unknown> = {}
    if (params.channel) payload.channel = params.channel
    if (params.thread_id) payload.thread_id = params.thread_id
    return request<CreateEventResponse>('/events', {
      method: 'POST',
      body: JSON.stringify({
        id: rid('raw'),
        type: params.type,
        timestamp: isoNow(),
        source: params.source,
        raw_text: params.text,
        payload,
      }),
    })
  },

  reviewState: () =>
    request<{ issues: unknown[]; executed: unknown[]; proposal: Proposal | null }>(
      '/review-state',
      { method: 'POST', body: JSON.stringify({}) },
    ),

  // Exec free-language Q&A (added in backend, see /ask).
  ask: (question: string) =>
    request<AskResponse>('/ask', {
      method: 'POST',
      body: JSON.stringify({ question }),
    }),
}
