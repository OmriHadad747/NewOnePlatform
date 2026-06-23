// Board view models: bucket tasks by status into columns, and resolve the
// dependency graph into "blocked by" / "blocks" relations per task. Bucketing
// uses the same lenient status vocabulary as the rest of the app.

import type { Entity, ProjectStateResponse } from './types'
import type { Tone } from './format'

export type Bucket = 'todo' | 'in_progress' | 'blocked' | 'done'

export const BUCKETS: { key: Bucket; label: string; tone: Tone }[] = [
  { key: 'todo', label: 'Not started', tone: 'muted' },
  { key: 'in_progress', label: 'In progress', tone: 'blue' },
  { key: 'blocked', label: 'Blocked', tone: 'red' },
  { key: 'done', label: 'Done', tone: 'green' },
]

const lc = (v: unknown) => String(v ?? '').toLowerCase().replace(/[\s-]+/g, '_')

export function bucketOf(status: unknown): Bucket {
  const s = lc(status)
  if (['done', 'complete', 'completed', 'finished', 'closed', 'resolved'].includes(s)) return 'done'
  if (['blocked', 'stuck', 'waiting', 'at_risk'].includes(s)) return 'blocked'
  if (['in_progress', 'active', 'doing', 'ongoing', 'started'].includes(s)) return 'in_progress'
  return 'todo'
}

export interface TaskItem {
  id: string
  entity: Entity
  blockedBy: string[] // task titles this task waits on (active deps)
  blocks: string[] // task titles waiting on this one
}

export interface DependencyEdge {
  from: string
  to: string
  active: boolean
}

const taskTitle = (state: ProjectStateResponse, id: string) =>
  state.Task?.[id]?.fields?.title || id

export function dependencyEdges(state: ProjectStateResponse): DependencyEdge[] {
  return Object.values(state.Dependency ?? {})
    .map((d) => ({
      from: String(d.fields.from_entity_id ?? ''),
      to: String(d.fields.to_entity_id ?? ''),
      active: lc(d.fields.status) !== 'resolved' && lc(d.fields.status) !== 'closed',
    }))
    .filter((e) => e.from && e.to)
}

export function buildBoard(state?: ProjectStateResponse): Record<Bucket, TaskItem[]> {
  const empty: Record<Bucket, TaskItem[]> = { todo: [], in_progress: [], blocked: [], done: [] }
  if (!state) return empty
  const edges = dependencyEdges(state)

  for (const [id, entity] of Object.entries(state.Task ?? {})) {
    const blockedBy = edges
      .filter((e) => e.from === id && e.active)
      .map((e) => taskTitle(state, e.to))
    const blocks = edges
      .filter((e) => e.to === id && e.active)
      .map((e) => taskTitle(state, e.from))
    // Bucket strictly by the task's own status; an active dependency is shown
    // as a "waiting on" indicator on the card rather than forcing the column,
    // so sequenced not-started work isn't misreported as blocked.
    empty[bucketOf(entity.fields.status)].push({ id, entity, blockedBy, blocks })
  }
  return empty
}
