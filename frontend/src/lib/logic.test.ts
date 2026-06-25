// Unit tests for the pure presentation/logic helpers — the layer that turns
// raw backend shapes into consistent view models. No DOM, no network.

import { describe, expect, it } from 'vitest'
import { taskStatus, severity, questionStatus, initials, personLabel, avatarTone } from './format'
import { bucketOf, buildBoard, dependencyEdges } from './board'
import { projectStats } from './health'
import { describeProposal, approverFor, proposalKind } from './proposal'
import { interpretApprovals } from './approvals'
import { reconstructThreads, threadTitle } from './threads'
import { describeEvent, groupByDay } from './events'
import type { AipmEvent, ProjectStateResponse, Proposal } from './types'

describe('format: status vocabulary is lenient', () => {
  it('maps task statuses to tone, treating "open" as not started', () => {
    expect(taskStatus('in_progress')).toEqual({ label: 'In progress', tone: 'blue' })
    expect(taskStatus('blocked')).toEqual({ label: 'Blocked', tone: 'red' })
    expect(taskStatus('done')).toEqual({ label: 'Done', tone: 'green' })
    expect(taskStatus('open')).toEqual({ label: 'Not started', tone: 'muted' })
    expect(taskStatus('')).toEqual({ label: 'No status', tone: 'muted' })
  })
  it('maps severities and unknowns sensibly', () => {
    expect(severity('high').tone).toBe('red')
    expect(severity('medium').tone).toBe('amber')
    expect(severity('low').tone).toBe('teal')
    expect(severity('').label).toBe('Unrated')
  })
  it('treats resolved-ish question statuses as closed', () => {
    expect(questionStatus('answered').tone).toBe('green')
    expect(questionStatus('').label).toBe('Open')
  })
})

describe('format: people', () => {
  it('derives labels and initials from emails or names', () => {
    expect(personLabel('alice@acme.com')).toBe('alice')
    expect(personLabel('')).toBe('Unassigned')
    expect(initials('data-scientist')).toBe('DS')
    expect(initials('alice bob')).toBe('AB')
    expect(initials('alice@acme.com')).toBe('AL')
  })
  it('avatar tone is deterministic', () => {
    expect(avatarTone('alice')).toBe(avatarTone('alice'))
  })
})

const stateFixture: ProjectStateResponse = {
  Task: {
    a: { fields: { title: 'A', status: 'in_progress', owner: 'alice' }, history: [] },
    b: { fields: { title: 'B', status: 'open', owner: 'bob' }, history: [] },
    c: { fields: { title: 'C', status: 'blocked', owner: 'carol' }, history: [] },
    d: { fields: { title: 'D', status: 'done', owner: 'dana' }, history: [] },
  },
  Risk: {
    r1: { fields: { severity: 'high', status: 'open' }, history: [] },
    r2: { fields: { severity: 'medium', status: 'resolved' }, history: [] },
  },
  OpenQuestion: { q1: { fields: { status: 'open' }, history: [] } },
  Dependency: {
    dep1: { fields: { from_entity_id: 'b', to_entity_id: 'a', status: 'active' }, history: [] },
  },
  actions: [],
  meta: { name: 'Test', team: ['alice', 'bob'], pm: 'pm@x.com' },
}

describe('board: bucketing + dependencies', () => {
  it('buckets by own status, not by dependency', () => {
    expect(bucketOf('open')).toBe('todo')
    const board = buildBoard(stateFixture)
    expect(board.in_progress.map((t) => t.id)).toEqual(['a'])
    expect(board.todo.map((t) => t.id)).toEqual(['b']) // b waits on a but stays todo
    expect(board.blocked.map((t) => t.id)).toEqual(['c'])
    expect(board.done.map((t) => t.id)).toEqual(['d'])
  })
  it('surfaces "waiting on" as an indicator', () => {
    const board = buildBoard(stateFixture)
    expect(board.todo[0].blockedBy).toEqual(['A'])
  })
  it('only counts active dependency edges', () => {
    expect(dependencyEdges(stateFixture)).toHaveLength(1)
  })
})

describe('health: derived stats', () => {
  it('counts tasks, risks, questions and a health label', () => {
    const s = projectStats(stateFixture)
    expect(s.tasksTotal).toBe(4)
    expect(s.tasksDone).toBe(1)
    expect(s.tasksBlocked).toBe(1)
    expect(s.risksOpen).toBe(1) // r2 resolved excluded
    expect(s.risksHigh).toBe(1)
    expect(s.openQuestions).toBe(1)
    expect(s.health.label).toBe('At risk') // a blocked task + a high risk
  })
  it('is on track with no blockers/risks', () => {
    expect(projectStats({ Task: { a: { fields: { status: 'done' }, history: [] } }, actions: [], meta: {} }).health.label).toBe('On track')
  })
})

const proposalFixture: Proposal = {
  id: 'prop_1',
  type: 'agent_proposal',
  timestamp: '2026-06-23T10:00:00Z',
  source: 'extraction:claude',
  raw_text: null,
  payload: {
    deltas: [{ op: 'update', entity_type: 'Task', entity_id: 'a', fields: { status: 'done', owner: 'alice' } }],
    actions: [{ type: 'raise_flag', category: 'consequential', payload: { entity_id: 'r1', reason: 'risky' }, source_event_id: '', asserted_by: '', asserted_at: '', source_span: null }],
    thread_id: 'thr_1',
  },
}

describe('proposal: view model + approver', () => {
  it('describes deltas and actions', () => {
    const v = describeProposal(proposalFixture)
    expect(v.deltas[0].verb).toBe('Update')
    expect(v.deltas[0].changes.some((c) => c.label === 'Status' && c.value === 'Done')).toBe(true)
    expect(v.actions[0].verb).toBe('Raise flag')
    expect(v.kind.label).toBe('Needs sign-off')
  })
  it('classifies a model revision', () => {
    expect(proposalKind({ ...proposalFixture, payload: { ...proposalFixture.payload, kind: 'model_revision' } }).label).toBe('Model correction')
  })
  it('picks an approver, falling back to team (matching backend)', () => {
    expect(approverFor(proposalFixture, { pm: 'pm@x.com' })).toBe('pm@x.com')
    expect(approverFor({ ...proposalFixture, payload: { ...proposalFixture.payload, approver: 'bob' } }, {})).toBe('bob')
    expect(approverFor(proposalFixture, {})).toBe('team')
  })
})

describe('approvals: outcome interpretation', () => {
  it('prioritizes a gated conflict over an approval', () => {
    expect(interpretApprovals({ approved: [1], gated: [1] }).title).toMatch(/contradiction/i)
  })
  it('reports approval, decline, and follow-up distinctly', () => {
    expect(interpretApprovals({ approved: [1] }).kind).toBe('success')
    expect(interpretApprovals({ rejected: [1] }).title).toBe('Declined')
    expect(interpretApprovals({ nudged: [1] }).title).toMatch(/followed up/i)
    expect(interpretApprovals({ error: 'boom' }).kind).toBe('error')
    expect(interpretApprovals(null).title).toBe('Nothing to resolve')
  })
})

const events: AipmEvent[] = [
  { id: 'e1', type: 'message_sent', timestamp: '2026-06-22T09:00:00Z', source: 'agent:claude', raw_text: null, payload: { payload: { to: 'bob', subject: 'Hi', body: 'You around?', thread_id: 't1' } } },
  { id: 'e2', type: 'message_received', timestamp: '2026-06-22T10:00:00Z', source: 'bob', raw_text: 'Yes!', payload: { thread_id: 't1' } },
]

describe('threads: reconstruction', () => {
  it('rebuilds a thread from message events with correct sides', () => {
    const t = reconstructThreads(events)
    expect(t).toHaveLength(1)
    expect(t[0].messages.map((m) => m.isAgent)).toEqual([true, false])
    expect(t[0].participants).toContain('bob')
  })
  it('flags open threads via pending proposals and cleans subjects', () => {
    const t = reconstructThreads(events, [{ ...proposalFixture, payload: { ...proposalFixture.payload, thread_id: 't1' } }])
    expect(t[0].open).toBe(true)
    expect(threadTitle({ ...t[0], subject: 'Re: Hi there' })).toBe('Hi there')
  })
})

describe('events: descriptions + grouping', () => {
  it('describes outbound events using the nested payload', () => {
    expect(describeEvent(events[0]).title).toMatch(/messaged bob/i)
    expect(describeEvent(events[1]).title).toMatch(/bob replied/i)
  })
  it('groups events by day, newest first', () => {
    const groups = groupByDay(events)
    expect(groups[0].events).toHaveLength(2)
  })
})
