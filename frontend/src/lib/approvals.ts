// Interpret the backend's approval-resolution result (the `approvals` field of
// POST /events for a threaded reply) into one friendly, human message. The
// engine can do a lot with a reply — approve, decline, amend, propose a
// correction, gate on a contradiction, fan out to owners — and we name each
// outcome plainly so the manager always knows what just happened.

import { AGENT_NAME } from './persona'

export interface ApprovalOutcome {
  kind: 'success' | 'error' | 'info'
  title: string
  description?: string
}

type ApprovalsResult = Record<string, any> | null

export function interpretApprovals(approvals: ApprovalsResult): ApprovalOutcome {
  if (!approvals) {
    return {
      kind: 'info',
      title: 'Nothing to resolve',
      description: `${AGENT_NAME} didn't find a pending request on this thread.`,
    }
  }
  if (approvals.error) {
    return {
      kind: 'error',
      title: `${AGENT_NAME} couldn't process that`,
      description: 'The model hit a snag resolving your reply. Give it another try.',
    }
  }

  const len = (k: string) => (Array.isArray(approvals[k]) ? approvals[k].length : 0)

  if (len('approved'))
    return { kind: 'success', title: 'Approved', description: `${AGENT_NAME} recorded the change.` }
  if (len('amended'))
    return {
      kind: 'success',
      title: 'Recorded as partial',
      description: `${AGENT_NAME} kept the honest, partial outcome.`,
    }
  if (len('revised'))
    return {
      kind: 'info',
      title: `${AGENT_NAME} drafted a correction`,
      description: 'It thinks the model was wrong and routed a fix to the PM.',
    }
  if (len('gated'))
    return {
      kind: 'info',
      title: 'One contradiction to confirm',
      description: `${AGENT_NAME} flagged an inconsistency. Reply "record it anyway" to accept it.`,
    }
  if (len('fanned_out'))
    return {
      kind: 'success',
      title: 'Sent to owners',
      description: 'Each ticket now waits on its owner to confirm.',
    }
  if (len('rejected'))
    return { kind: 'info', title: 'Declined', description: `${AGENT_NAME} closed the proposal.` }

  return {
    kind: 'info',
    title: 'Got it',
    description: `${AGENT_NAME} didn't read that as a clear yes or no — try rephrasing.`,
  }
}
