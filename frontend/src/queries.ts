/**
 * TanStack Query hooks — one per server resource.
 *
 * Polling stops while the document is hidden (FR-9.8). Mutations in later slices
 * invalidate these keys instead of patching the cache.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './api'
import type {
  DecisionKind,
  ItemDetail,
  ItemsPage,
  JobLogs,
  JobView,
  QueueView,
  SessionView,
  SyncView,
  WorkflowView,
} from './api'

const visible = (): boolean => !document.hidden

/** Poll only when the tab is visible and the last fetch succeeded. */
function poll(ms: number): (query: { state: { status: string } }) => number | false {
  return (query) => (visible() && query.state.status === 'success' ? ms : false)
}

/** Deck/list filters. `statuses` is the repeatable `?status=` filter. */
export interface ItemFilters {
  statuses?: string[]
  decision?: string
  q?: string
}

export const keys = {
  workflows: ['workflows'] as const,
  session: ['session'] as const,
  sync: (route: string) => ['sync', route] as const,
  items: (route: string, filters: ItemFilters) => ['items', route, filters] as const,
  item: (route: string, key: string) => ['item', route, key] as const,
  jobs: (limit: number) => ['jobs', limit] as const,
  jobLogs: (id: number) => ['job', id] as const,
  workers: ['workers'] as const,
}

export function useWorkflows(): ReturnType<typeof useQuery<WorkflowView[]>> {
  return useQuery({ queryKey: keys.workflows, queryFn: () => api.workflows(), staleTime: Infinity })
}

export function useSession(): ReturnType<typeof useQuery<SessionView>> {
  return useQuery({ queryKey: keys.session, queryFn: () => api.session(), refetchInterval: poll(10_000) })
}

export function useSync(route: string | null): ReturnType<typeof useQuery<SyncView | null>> {
  return useQuery({
    queryKey: keys.sync(route ?? ''),
    queryFn: () => api.sync(route ?? ''),
    enabled: route !== null,
    refetchInterval: poll(10_000),
  })
}

export function useItems(
  route: string | null,
  filters: ItemFilters,
  limit = 200,
  enabled = true,
): ReturnType<typeof useQuery<ItemsPage>> {
  return useQuery({
    queryKey: keys.items(route ?? '', filters),
    queryFn: () => api.items(route ?? '', { ...filters, limit }),
    enabled: route !== null && enabled,
    refetchInterval: poll(10_000),
  })
}

export function useItem(route: string | null, key: string | null): ReturnType<typeof useQuery<ItemDetail>> {
  return useQuery({
    queryKey: keys.item(route ?? '', key ?? ''),
    queryFn: () => api.item(route ?? '', key ?? ''),
    enabled: route !== null && key !== null,
    refetchInterval: poll(10_000),
  })
}

export function useJobs(limit = 50): ReturnType<typeof useQuery<JobView[]>> {
  return useQuery({ queryKey: keys.jobs(limit), queryFn: () => api.jobs({ limit }), refetchInterval: poll(2_000) })
}

export function useJobLogs(id: number | null): ReturnType<typeof useQuery<JobLogs>> {
  return useQuery({
    queryKey: keys.jobLogs(id ?? 0),
    queryFn: () => api.jobLogs(id ?? 0),
    enabled: id !== null,
    refetchInterval: poll(2_000),
  })
}

export function useWorkers(): ReturnType<typeof useQuery<QueueView>> {
  return useQuery({ queryKey: keys.workers, queryFn: () => api.workers(), refetchInterval: poll(5_000) })
}

export function useLogin(): ReturnType<typeof useMutation<SessionView>> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.login(),
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.session }),
  })
}

export function useLogout(): ReturnType<typeof useMutation<void>> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.logout(),
    onSuccess: () => void client.invalidateQueries(),
  })
}

/** Record an accept/reject decision; the list and item caches are invalidated. */
export function useDecideDecision(
  route: string | null,
): ReturnType<typeof useMutation<ItemDetail, Error, { key: string; decision: DecisionKind; reason?: string }>> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ key, decision, reason }) =>
      api.decide(route ?? '', key, decision, reason),
    onSuccess: (_detail, { key }) => {
      if (route === null) return
      void client.invalidateQueries({ queryKey: ['items', route] })
      void client.invalidateQueries({ queryKey: keys.item(route, key) })
    },
  })
}

/** Undo the current decision: the item becomes undecided and re-enters the deck. */
export function useUndoDecision(
  route: string | null,
): ReturnType<typeof useMutation<ItemDetail, Error, { key: string }>> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ key }) => api.undoDecision(route ?? '', key),
    onSuccess: (_detail, { key }) => {
      if (route === null) return
      void client.invalidateQueries({ queryKey: ['items', route] })
      void client.invalidateQueries({ queryKey: keys.item(route, key) })
    },
  })
}

export function useRequestSync(
  route: string | null,
): ReturnType<typeof useMutation<{ status: string; workflow: string }>> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.requestSync(route ?? ''),
    onSuccess: () => {
      if (route !== null) void client.invalidateQueries({ queryKey: keys.sync(route) })
    },
  })
}
