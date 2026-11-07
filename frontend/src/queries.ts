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
  DevQueryView,
  DevTablesView,
  HistoryPage,
  ItemDetail,
  ItemsPage,
  JobLogs,
  JobsPage,
  JobView,
  NetworkView,
  PurgeResult,
  PurgeScope,
  QueueView,
  SessionView,
  SyncView,
  UpdateStatus,
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
  ids: string[]
  statusText: string
  statuses: string[]
  kindText: string
  kinds: string[]
  phaseText: string
  phases: string[]
  item: string
  items: string[]
  error: string
  errors: string[]
  startedAfter: string
  startedBefore: string
  durationMinS: string
  durationMaxS: string
}

export const EMPTY_JOB_FILTERS: JobFilters = {
  id: '',
  ids: [],
  statusText: '',
  statuses: [],
  kindText: '',
  kinds: [],
  phaseText: '',
  phases: [],
  item: '',
  items: [],
  error: '',
  errors: [],
  startedAfter: '',
  startedBefore: '',
  durationMinS: '',
  durationMaxS: '',
}

/** Approved-history filter row; field maps are keyed by catalogue field key. */
export interface HistoryFilters {
  key: string
  keys: string[]
  statusText: string
  statuses: string[]
  approved: string
  approvedValues: string[]
  decidedAfter: string
  decidedBefore: string
  fieldText: Record<string, string>
  fieldValues: Record<string, string[]>
  refText: Record<string, string>
  refValues: Record<string, string[]>
}

export const EMPTY_HISTORY_FILTERS: HistoryFilters = {
  key: '',
  keys: [],
  statusText: '',
  statuses: [],
  approved: '',
  approvedValues: [],
  decidedAfter: '',
  decidedBefore: '',
  fieldText: {},
  fieldValues: {},
  refText: {},
  refValues: {},
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

/** Approved-history rows; a separate snapshot read model from the deck. */
export function useHistory(
  route: string | null,
  filters: HistoryFilters,
  limit = 25,
  enabled = true,
  offset = 0,
): ReturnType<typeof useQuery<HistoryPage>> {
  return useQuery({
    queryKey: ['history', route ?? '', JSON.stringify(filters), offset, limit],
    queryFn: () =>
      api.history(route ?? '', {
        key: filters.key || undefined,
        keyIn: filters.keys.length > 0 ? filters.keys : undefined,
        statusText: filters.statusText || undefined,
        statuses: filters.statuses.length > 0 ? filters.statuses : undefined,
        approvedAt: filters.approved || undefined,
        approvedAtIn:
          filters.approvedValues.length > 0 ? filters.approvedValues : undefined,
        decidedAfter: filters.decidedAfter || undefined,
        decidedBefore: filters.decidedBefore || undefined,
        fields: Object.entries(filters.fieldValues).flatMap(([key, values]) =>
          values.map((value) => ({ key, value })),
        ),
        fieldText: Object.entries(filters.fieldText)
          .filter(([, text]) => text.trim() !== '')
          .map(([key, text]) => ({ key, text })),
        refs: Object.entries(filters.refValues).flatMap(([kind, values]) =>
          values.map((value) => ({ kind, value })),
        ),
        refText: Object.entries(filters.refText)
          .filter(([, text]) => text.trim() !== '')
          .map(([kind, text]) => ({ kind, text })),
        limit,
        offset,
      }),
    enabled: route !== null && enabled,
    refetchInterval: poll(10_000),
  })
}

/** One read-only approved-history detail. */
export function useHistoryItem(
  route: string | null,
  key: string | null,
): ReturnType<typeof useQuery<ItemDetail>> {
  return useQuery({
    queryKey: ['history-item', route ?? '', key ?? ''],
    queryFn: () => api.historyItem(route ?? '', key ?? ''),
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
        idIn: filters.ids.length > 0 ? filters.ids : undefined,
        statusText: filters.statusText || undefined,
        status: filters.statuses.length > 0 ? filters.statuses : undefined,
        kindText: filters.kindText || undefined,
        kind: filters.kinds.length > 0 ? filters.kinds : undefined,
        phaseText: filters.phaseText || undefined,
        phase: filters.phases.length > 0 ? filters.phases : undefined,
        item: filters.item || undefined,
        itemIn: filters.items.length > 0 ? filters.items : undefined,
        error: filters.error || undefined,
        errorIn: filters.errors.length > 0 ? filters.errors : undefined,
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
  return useQuery({
    queryKey: keys.workers,
    queryFn: () => api.workers(),
    refetchInterval: poll(5_000),
  })
}

export function useNetwork(): ReturnType<typeof useQuery<NetworkView>> {
  return useQuery({
    queryKey: ['network'],
    queryFn: () => api.network(),
    refetchInterval: poll(10_000),
  })
}

export function useUpdates(): ReturnType<typeof useQuery<UpdateStatus>> {
  return useQuery({
    queryKey: ['updates'],
    queryFn: () => api.updates(),
    refetchInterval: poll(10_000),
  })
}

export function useInstallUpdate(): ReturnType<typeof useMutation<UpdateStatus>> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.installUpdate(),
    onSuccess: (status) => client.setQueryData(['updates'], status),
  })
}

/**
 * Force an update check after a failure.
 *
 * A failed check is never cached server-side, but the card has no other way to retry
 * before the 10-minute auto loop tick; the response replaces the shown status.
 */
export function useCheckUpdate(): ReturnType<typeof useMutation<UpdateStatus>> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.checkUpdate(),
    onSuccess: (status) => client.setQueryData(['updates'], status),
  })
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
      void client.invalidateQueries({ queryKey: ['history', route] })
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

/** Enqueue the single SUBMIT job after an accept; refresh deck, detail and jobs. */
export function useSubmitJob(
  route: string | null,
): ReturnType<typeof useMutation<JobView, Error, { key: string }>> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ key }) => api.submitJob(route ?? '', key),
    onSuccess: (_job, { key }) => {
      if (route === null) return
      void client.invalidateQueries({ queryKey: ['items', route] })
      void client.invalidateQueries({ queryKey: ['history', route] })
      void client.invalidateQueries({ queryKey: keys.item(route, key) })
      void client.invalidateQueries({ queryKey: ['jobs'] })
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
      void client.invalidateQueries({ queryKey: ['history', route] })
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
    // A refusal (`login_required`) means the session is no longer usable: refresh the
    // banner now instead of leaving a stale "active" state until the next poll (D-07).
    onError: () => {
      void client.invalidateQueries({ queryKey: keys.session })
    },
  })
}

/** Dev-only DB explorer: table metadata, preview query and file export. */
export function useDevTables(): ReturnType<typeof useQuery<DevTablesView>> {
  return useQuery({
    queryKey: ['dev', 'db', 'tables'],
    queryFn: () => api.devTables(),
    retry: false,
  })
}

export function useDevQuery(): ReturnType<
  typeof useMutation<DevQueryView, Error, { sql: string; limit?: number }>
> {
  return useMutation({
    mutationFn: ({ sql, limit }) => api.devQuery(sql, limit),
  })
}

export function useDevExport(): ReturnType<
  typeof useMutation<Blob, Error, { sql: string; format: 'csv' | 'xlsx' }>
> {
  return useMutation({
    mutationFn: ({ sql, format }) => api.devExport(sql, format),
  })
}

/** Manual retention action; call with ``dryRun`` first, then again to delete. */
export function useDevPurge(): ReturnType<
  typeof useMutation<PurgeResult, Error, { scope: PurgeScope; dryRun: boolean }>
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ scope, dryRun }) => api.devPurge(scope, dryRun),
    onSuccess: (result) => {
      if (result.dryRun) return
      void client.invalidateQueries({ queryKey: ['dev', 'db', 'tables'] })
    },
  })
}
