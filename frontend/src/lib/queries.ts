// React Query hooks over the API client. Centralizes caching, polling, and the
// resilient retry/backoff the platform needs when the live LLM or backend
// hiccups. Mutations invalidate the relevant queries so every screen stays in
// sync after an approval/feed without a manual refresh.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './api'
import type { ProjectInput } from './types'

export const qk = {
  project: ['project'] as const,
  state: ['state'] as const,
  events: ['events'] as const,
  proposals: ['proposals'] as const,
}

// Retry transient failures (network + 5xx + LLM 502), but never client errors
// (4xx) — those won't fix themselves on retry.
function retry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
  return failureCount < 3
}
const retryDelay = (attempt: number) => Math.min(1000 * 2 ** attempt, 8000)

// staleTime below the poll intervals so a scheduled refetch is never served
// stale from cache.
const common = { retry, retryDelay, staleTime: 2000 }

export function useProject() {
  return useQuery({ queryKey: qk.project, queryFn: api.getProject, ...common })
}
export function useProjectState(opts?: { poll?: boolean }) {
  return useQuery({
    queryKey: qk.state,
    queryFn: api.getState,
    refetchInterval: opts?.poll ? 5000 : false,
    ...common,
  })
}
export function useEvents(opts?: { poll?: boolean }) {
  return useQuery({
    queryKey: qk.events,
    queryFn: api.getEvents,
    refetchInterval: opts?.poll ? 4000 : false,
    ...common,
  })
}
export function useProposals(opts?: { poll?: boolean }) {
  return useQuery({
    queryKey: qk.proposals,
    queryFn: api.getProposals,
    refetchInterval: opts?.poll ? 4000 : false,
    ...common,
  })
}

export function useInvalidateAll() {
  const qc = useQueryClient()
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: qk.state }),
      qc.invalidateQueries({ queryKey: qk.events }),
      qc.invalidateQueries({ queryKey: qk.proposals }),
      qc.invalidateQueries({ queryKey: qk.project }),
    ])
}

export function useAddRawEvent() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: api.addRawEvent,
    retry,
    retryDelay,
    onSuccess: () => invalidate(),
  })
}

export function useInitProject() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: ProjectInput) => api.initProject(body),
    retry,
    retryDelay,
    onSuccess: () => invalidate(),
  })
}

export function useAsk() {
  return useMutation({ mutationFn: (q: string) => api.ask(q), retry, retryDelay })
}
