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
  JobsPage,
  QueueView,
  SessionView,
  SyncView,
  VersionView,
  WorkflowView,
} from './api'

const visible = (): boolean => !document.hidden

/**
 * Poll while the tab is visible, including after a failed request.
 *
 * Freezing on error used to hide a recovered backend: one failed poll during a restart
 * stopped all polling and left a stale sync banner on screen forever (FR-9.8).
 */
function poll(ms: number): () => number | false {
  return () => (visible() ? ms : false)
}

/** Jobs-table filters. Durations are entered in seconds, sent in ms. */
export interface JobFilters {
  id: string
  status: string
  kind: string
  phase: string
  item: string
  error: string
  startedAfter: string
  startedBefore: string
  durationMinS: string
  durationMaxS: string
}

/** Deck/list filters. `statuses` is the repeatable `?status=` filter. */
export interface ItemFilters {
  statuses?: string[]
  decision?: string
  q?: string
  sort?: string
  order?: string
}

export const keys = {
  workflows: ['workflows'] as const,
  version: ['version'] as const,
  session: ['session'] as const,
  sync: (route: string) => ['sync', route] as const,
  items: (route: string, filters: ItemFilters, offset = 0) =>
    ['items', route, filters, offset] as const,
  item: (route: string, key: string) => ['item', route, key] as const,
  jobs: (
    filters: JobFilters,
    page: number,
    size: number,
    sort: string,
    order: string,
  ) => ['jobs', filters, page, size, sort, order] as const,
  jobLogs: (id: number) => ['job', id] as const,
  workers: ['workers'] as const,
}

export function useWorkflows(): ReturnType<typeof useQuery<WorkflowView[]>> {
  return useQuery({ queryKey: keys.workflows, queryFn: () => api.workflows(), staleTime: Infinity })
}

export function useVersion(): ReturnType<typeof useQuery<VersionView>> {
  return useQuery({ queryKey: keys.version, queryFn: () => api.version(), staleTime: Infinity })
}

export function useSession(): ReturnType<typeof useQuery<SessionView>> {
  return useQuery({ queryKey: keys.session, queryFn: () => api.session(), refetchInterval: poll(10_000) })
}

export function useSync(workflow: string | null): ReturnType<typeof useQuery<SyncView | null>> {
  return useQuery({
    queryKey: keys.sync(workflow ?? ''),
    queryFn: () => api.sync(workflow ?? ''),
    enabled: workflow !== null,
    refetchInterval: poll(10_000),
  })
}

export function useItems(
  route: string | null,
  filters: ItemFilters,
  limit = 200,
  enabled = true,
  offset = 0,
): ReturnType<typeof useQuery<ItemsPage>> {
  return useQuery({
    queryKey: keys.items(route ?? '', filters, offset),
    queryFn: () => api.items(route ?? '', { ...filters, limit, offset }),
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

export function useJobs(
  filters: JobFilters,
  page: number,
  size: number,
  sort: string,
  order: string,
): ReturnType<typeof useQuery<JobsPage>> {
  const seconds = (value: string): number | undefined => {
    const parsed = Number(value)
    return value.trim() !== '' && Number.isFinite(parsed) && parsed >= 0
      ? Math.round(parsed * 1000)
      : undefined
  }
  return useQuery({
    queryKey: keys.jobs(filters, page, size, sort, order),
    placeholderData: (previous) => previous,
    queryFn: () =>
      api.jobs({
        id: filters.id || undefined,
        status: filters.status || undefined,
        kind: filters.kind || undefined,
        phase: filters.phase || undefined,
        item: filters.item || undefined,
        error: filters.error || undefined,
        startedAfter: filters.startedAfter || undefined,
        startedBefore: filters.startedBefore || undefined,
        durationMinMs: seconds(filters.durationMinS),
        durationMaxMs: seconds(filters.durationMaxS),
        sort,
        order,
        limit: size,
        offset: (page - 1) * size,
      }),
    refetchInterval: poll(2_000),
  })
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

/** Propose edited values; the authoritative detail comes back in the response. */
export function usePatchFields(
  route: string | null,
): ReturnType<typeof useMutation<ItemDetail, Error, { key: string; changes: Record<string, string | null> }>> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ key, changes }) => api.patchFields(route ?? '', key, changes),
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
  workflow: string | null,
): ReturnType<typeof useMutation<{ status: string; workflow: string }>> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.requestSync(workflow ?? ''),
    onSuccess: () => {
      if (workflow !== null) void client.invalidateQueries({ queryKey: keys.sync(workflow) })
    },
  })
}
