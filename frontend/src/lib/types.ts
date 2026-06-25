// Types mirroring the FastAPI backend (backend/src/aipm_backend) and the
// ai-engine data model. Kept deliberately close to the wire shapes so the
// client never guesses: see backend/README.md and ai-engine/src/aipm.

export const ENTITY_TYPES = [
  'Task',
  'Risk',
  'Decision',
  'Owner',
  'Deadline',
  'Dependency',
  'OpenQuestion',
] as const
export type EntityType = (typeof ENTITY_TYPES)[number]

export interface ProvenanceRecord {
  fields_changed: Record<string, unknown>
  source_event_id: string
  asserted_by: string
  asserted_at: string
  confidence: number
  source_span: string | null
}

export interface Entity {
  fields: Record<string, any>
  history: ProvenanceRecord[]
}

export interface Action {
  type: string
  category: 'info_request' | 'consequential'
  payload: Record<string, any>
  source_event_id: string
  asserted_by: string
  asserted_at: string
  source_span: string | null
}

export interface ProjectMeta {
  name?: string
  description?: string
  team?: string[]
  start_date?: string
  end_date?: string
  pm?: string
  tech_lead?: string
  status?: string
  [k: string]: unknown
}

// POST /project body (backend ProjectIn): `name` is required, the rest optional.
// Narrower than ProjectMeta (the GET response) so a missing name is a compile
// error at the call site.
export interface ProjectInput {
  name: string
  description?: string
  team?: string[]
  start_date?: string
  end_date?: string
  pm?: string
  tech_lead?: string
}

// GET /state — one map per entity type, plus actions + meta.
export interface ProjectStateResponse {
  Task?: Record<string, Entity>
  Risk?: Record<string, Entity>
  Decision?: Record<string, Entity>
  Owner?: Record<string, Entity>
  Deadline?: Record<string, Entity>
  Dependency?: Record<string, Entity>
  OpenQuestion?: Record<string, Entity>
  actions: Action[]
  meta: ProjectMeta
}

export type EventType =
  | 'project_initialized'
  | 'project_closed'
  | 'transcript_ingested'
  | 'message_received'
  | 'manual_note'
  | 'agent_proposal'
  | 'human_approval'
  | 'proposal_rejected'
  | 'message_sent'
  | 'ticket_opened'
  | 'flag_raised'
  | 'report_to_management'

export interface AipmEvent {
  id: string
  type: EventType
  timestamp: string
  source: string
  raw_text: string | null
  payload: Record<string, any>
}

export interface ProposalDelta {
  op: 'create' | 'update' | 'delete'
  entity_type: EntityType
  entity_id: string
  fields?: Record<string, any>
}

export interface Proposal extends AipmEvent {
  type: 'agent_proposal'
  payload: {
    deltas?: ProposalDelta[]
    actions?: Action[]
    thread_id?: string
    provider?: string
    source_event_id?: string
    approver?: string
    kind?: string
    rationale?: string
    supersedes?: string
    [k: string]: any
  }
}

export interface Conflict {
  type: string
  entity_id: string
  detail: string
}

// Shape returned by POST /events (and /extract) under `extraction`.
export interface ExtractionResult {
  proposal: Proposal | null
  approval_request?: AipmEvent | null
  dropped?: unknown[]
  executed?: AipmEvent[]
  conflicts?: Conflict[]
  clarifications?: unknown[]
  skipped?: string
  error?: string
}

export interface CreateEventResponse extends AipmEvent {
  approvals: Record<string, any> | null
  extraction: ExtractionResult | null
  reopen_hint: AipmEvent | null
}

export interface ReviewIssue {
  rule: string
  entity_type: string
  entity_id: string
  detail: string
}

export interface AskResponse {
  answer: string
  model?: string
}
