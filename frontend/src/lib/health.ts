// Derived project health — computed from state the same way everywhere so the
// header pill, the exec overview, and any summary agree. State is derived from
// the event log on the backend; this is a thin presentational read of it.

import type { ProjectStateResponse } from './types'
import type { Tone } from './format'

const lc = (v: unknown) => String(v ?? '').toLowerCase()
const DONE = ['done', 'complete', 'completed', 'finished', 'closed', 'resolved']
const BLOCKED = ['blocked', 'stuck']
const HIGH = ['high', 'critical']
const OPEN_RISK = ['resolved', 'closed', 'mitigated', 'accepted', 'retired']

export interface ProjectStats {
  tasksTotal: number
  tasksDone: number
  tasksInProgress: number
  tasksBlocked: number
  tasksNotStarted: number
  risksOpen: number
  risksHigh: number
  openQuestions: number
  decisions: number
  overdue: number
  health: { label: string; tone: Tone }
}

export function projectStats(state?: ProjectStateResponse): ProjectStats {
  const tasks = Object.values(state?.Task ?? {})
  const risks = Object.values(state?.Risk ?? {})
  const questions = Object.values(state?.OpenQuestion ?? {})
  const deadlines = Object.values(state?.Deadline ?? {})

  let done = 0,
    prog = 0,
    blocked = 0,
    notStarted = 0
  for (const t of tasks) {
    const s = lc(t.fields.status)
    if (DONE.some((d) => s.includes(d))) done++
    else if (BLOCKED.some((d) => s.includes(d))) blocked++
    else if (s.includes('progress') || s === 'active') prog++
    else notStarted++
  }

  const openRisks = risks.filter((r) => !OPEN_RISK.includes(lc(r.fields.status)))
  const risksHigh = openRisks.filter((r) => HIGH.includes(lc(r.fields.severity))).length

  const today = new Date().toISOString().slice(0, 10)
  const overdue = deadlines.filter((d) => {
    const due = String(d.fields.due_date ?? '')
    return due && due < today
  }).length

  const openQuestions = questions.filter(
    (q) => !['resolved', 'closed', 'answered', 'decided', 'done'].includes(lc(q.fields.status)),
  ).length

  let health: ProjectStats['health'] = { label: 'On track', tone: 'green' }
  if (blocked > 0 || overdue > 0 || risksHigh > 0) health = { label: 'At risk', tone: 'amber' }
  if ((blocked >= 2 && tasks.length > 0) || overdue >= 2) health = { label: 'Needs attention', tone: 'red' }
  if (state?.meta?.status === 'closed') health = { label: 'Closed', tone: 'muted' }

  return {
    tasksTotal: tasks.length,
    tasksDone: done,
    tasksInProgress: prog,
    tasksBlocked: blocked,
    tasksNotStarted: notStarted,
    risksOpen: openRisks.length,
    risksHigh,
    openQuestions,
    decisions: Object.keys(state?.Decision ?? {}).length,
    overdue,
    health,
  }
}
