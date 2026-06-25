// Manager cockpit: the approvals inbox. Each pending proposal is a decision;
// approving/declining/replying sends a message on the proposal's thread, which
// the engine resolves (the one and only approval path). A project-pulse rail
// keeps health in view while you clear the queue.

import { AnimatePresence } from 'framer-motion'
import { PartyPopper } from 'lucide-react'
import { useState } from 'react'
import { ProjectPulse } from '../components/ProjectPulse'
import { ProposalCard } from '../components/proposals/ProposalCard'
import { PageContainer, PageHeader } from '../components/PageHeader'
import { useToast } from '../components/Toast'
import { Card, EmptyState, ErrorState, Skeleton } from '../components/ui'
import { interpretApprovals } from '../lib/approvals'
import { approverFor } from '../lib/proposal'
import { AGENT_NAME } from '../lib/persona'
import { useAddRawEvent, useProject, useProposals } from '../lib/queries'
import type { Proposal } from '../lib/types'

export function Manager() {
  const proposalsQ = useProposals({ poll: true })
  const { data: project } = useProject()
  const reply = useAddRawEvent()
  const toast = useToast()
  const [busyId, setBusyId] = useState<string | null>(null)
  // Proposals resolved this session — hidden immediately so a card can't be
  // acted on twice in the window before the poll/invalidation catches up.
  const [resolvedIds, setResolvedIds] = useState<Set<string>>(new Set())

  const proposals = (proposalsQ.data ?? []).filter((p) => !resolvedIds.has(p.id))

  const send = async (proposal: Proposal, text: string) => {
    const thread_id = proposal.payload.thread_id
    const source = approverFor(proposal, project)
    setBusyId(proposal.id)
    try {
      const res = await reply.mutateAsync({
        type: 'message_received',
        text,
        source,
        channel: 'stub',
        thread_id,
      })
      const outcome = interpretApprovals(res.approvals)
      toast[outcome.kind](outcome.title, outcome.description)
      // Hide the card only if the engine actually closed it (a follow-up/defer
      // leaves it pending, so keep it visible to act on again).
      const a = res.approvals
      const settled =
        a && ['approved', 'rejected', 'amended', 'revised', 'fanned_out'].some((k) => a[k]?.length)
      if (settled) setResolvedIds((s) => new Set(s).add(proposal.id))
    } catch {
      toast.error(
        `${AGENT_NAME} didn't respond`,
        'The reply could not be delivered. Please try again.',
        { label: 'Retry', onClick: () => send(proposal, text) },
      )
    } finally {
      setBusyId(null)
    }
  }

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Manager"
        title="Approvals"
        subtitle={`Review what ${AGENT_NAME} proposes. Approving or declining is a reply on the thread — exactly how the agent works.`}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          {proposalsQ.isLoading ? (
            <div className="flex flex-col gap-4">
              <Skeleton className="h-44 w-full" />
              <Skeleton className="h-44 w-full" />
            </div>
          ) : proposalsQ.isError ? (
            <Card>
              <ErrorState
                title={`Couldn't load the queue`}
                description={`${AGENT_NAME} couldn't fetch pending proposals. The backend may be waking up.`}
                onRetry={() => proposalsQ.refetch()}
                retrying={proposalsQ.isFetching}
              />
            </Card>
          ) : proposals.length === 0 ? (
            <Card>
              <EmptyState
                icon={PartyPopper}
                title="All clear"
                description={`Nothing needs your sign-off right now. ${AGENT_NAME} will surface proposals here as work comes in.`}
              />
            </Card>
          ) : (
            <div className="flex flex-col gap-4">
              <AnimatePresence mode="popLayout">
                {proposals.map((p) => (
                  <ProposalCard key={p.id} proposal={p} busy={busyId === p.id} onSend={(t) => send(p, t)} />
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>

        <aside className="lg:sticky lg:top-6 lg:self-start">
          <ProjectPulse />
        </aside>
      </div>
    </PageContainer>
  )
}
