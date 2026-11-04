/**
 * TanStack Query hooks — one per server resource.
 *
 * Polling stops while the document is hidden (FR-9.8). Mutations in later slices
 * invalidate these keys instead of patching the cache.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './api'
import type { ItemDetail, ItemsPage, JobLogs, JobView, QueueView, SessionView, SyncView, WorkflowView } from './api'

const visible = (): boolean => !document.hidden

/** Poll only when the tab is visible and the last fetch succeeded. */
function poll(ms: number): (query: { state: { status: string } }) => number | false {
  return (query) => (visible() && query.state.status === 'success' ? ms : false)
}

export const keys = {
  workflows: ['workflows'] as const,
  session: ['session'] as const,
  sync: (route: string) => ['sync', route] as const,
  items: (route: string, status: string, q: string) => ['items', route, status, q] as const,
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

export function useItems(route: string | null, status: string, q: string): ReturnType<typeof useQuery<ItemsPage>> {
  return useQuery({
    queryKey: keys.items(route ?? '', status, q),
    queryFn: () => api.items(route ?? '', { status: status || undefined, q: q || undefined, limit: 200 }),
    enabled: route !== null,
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
