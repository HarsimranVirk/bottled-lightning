/**
 * The only module that knows URL shapes.
 *
 * Every value type here is a generated schema type; the aliases below are the vocabulary
 * the UI uses. Errors are normalised into {@link ApiError} so components never inspect
 * status codes or raw payloads.
 */

import type { components } from './types'

export type WorkflowView = components['schemas']['WorkflowView']
export type WorkflowFieldView = components['schemas']['WorkflowFieldView']
export type ItemRow = components['schemas']['ItemRowView']
export type ItemDetail = components['schemas']['ItemDetailView']
export type ItemsPage = components['schemas']['ItemsPageView']
export type HistoryRow = components['schemas']['HistoryRowView']
export type HistoryPage = components['schemas']['HistoryPageView']
export type FieldView = components['schemas']['FieldView']
export type DecisionView = components['schemas']['DecisionView']
export type DecisionKind = DecisionView['decision']
export type PageRefView = components['schemas']['PageRefView']
export type JobView = components['schemas']['JobView']
export type JobLogs = components['schemas']['JobLogsView']
export type JobsPage = components['schemas']['JobsPageView']
export type SessionView = components['schemas']['SessionView']
export type SyncView = components['schemas']['SyncView']
export type QueueView = components['schemas']['QueueView']
export type VersionView = components['schemas']['VersionView']
export type DevTableView = components['schemas']['DevTableView']
export type DevTablesView = components['schemas']['DevTablesView']
export type DevQueryView = components['schemas']['DevQueryView']
export type DevCell = DevQueryView['rows'][number][number]
export type PurgeScope = components['schemas']['PurgeIn']['scope']
export type PurgeResult = components['schemas']['PurgeView']
export type NetworkView = components['schemas']['NetworkView']
export type UpdateStatus = components['schemas']['UpdateStatusView']

/** A failed request, normalised from the API's `{detail: {code, message}}` body. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string | null

  constructor(status: number, message: string, code: string | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

/** Read the documented error envelope, tolerating anything else. */
export function readDetail(status: number, body: unknown): { message: string; code: string | null } {
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const detail = body.detail
    if (typeof detail === 'string') {
      return { message: detail, code: null }
    }
    if (typeof detail === 'object' && detail !== null) {
      const message =
        'message' in detail && typeof detail.message === 'string'
          ? detail.message
          : `request failed (${status})`
      const code = 'code' in detail && typeof detail.code === 'string' ? detail.code : null
      return { message, code }
    }
  }
  return { message: `request failed (${status})`, code: null }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...init?.headers },
  })
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const { message, code } = readDetail(response.status, body)
    throw new ApiError(response.status, message, code)
  }
  return body as T
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  const response = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const { message, code } = readDetail(response.status, body)
    throw new ApiError(response.status, message, code)
  }
  return response.blob()
}

async function requestVoid(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const { message, code } = readDetail(response.status, body)
    throw new ApiError(response.status, message, code)
  }
}

/** Query for the jobs table; camelCase here, snake_case on the wire. */
export interface JobQuery {
  workflow?: string
  kind?: string[]
  status?: string[]
  phase?: string[]
  statusText?: string
  kindText?: string
  phaseText?: string
  item?: string
  itemIn?: string[]
  id?: string
  idIn?: string[]
  error?: string
  errorIn?: string[]
  startedAfter?: string
  startedBefore?: string
  durationMinMs?: number
  durationMaxMs?: number
  sort?: string
  order?: string
  limit?: number
  offset?: number
}

function jobsQuery(params: JobQuery): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue
    const wire =
      key === 'startedAfter'
        ? 'started_after'
        : key === 'startedBefore'
          ? 'started_before'
          : key === 'durationMinMs'
            ? 'duration_min_ms'
            : key === 'durationMaxMs'
              ? 'duration_max_ms'
              : key === 'itemIn'
                ? 'item_in'
                : key === 'idIn'
                  ? 'id_in'
                  : key === 'errorIn'
                    ? 'error_in'
                    : key === 'statusText'
                      ? 'status_text'
                      : key === 'kindText'
                        ? 'kind_text'
                        : key === 'phaseText'
                          ? 'phase_text'
                          : key
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== '') search.append(wire, item)
      }
    } else {
      search.set(wire, String(value))
    }
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

/** Standard History filter row; repeated values become repeated query params. */
export interface HistoryQuery {
  q?: string
  key?: string
  keyIn?: string[]
  statusText?: string
  statuses?: string[]
  approvedAt?: string
  approvedAtIn?: string[]
  decidedAfter?: string
  decidedBefore?: string
  fields?: { key: string; value: string }[]
  fieldText?: { key: string; text: string }[]
  refs?: { kind: string; value: string }[]
  refText?: { kind: string; text: string }[]
  limit?: number
  offset?: number
}

function historyQuery(params: HistoryQuery): string {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  if (params.key) search.set('key', params.key)
  for (const value of params.keyIn ?? []) search.append('key_in', value)
  if (params.statusText) search.set('status_text', params.statusText)
  for (const value of params.statuses ?? []) search.append('status', value)
  if (params.approvedAt) search.set('approved_at', params.approvedAt)
  for (const value of params.approvedAtIn ?? []) {
    search.append('approved_at_in', value)
  }
  if (params.decidedAfter) search.set('decided_after', params.decidedAfter)
  if (params.decidedBefore) search.set('decided_before', params.decidedBefore)
  for (const filter of params.fields ?? []) {
    search.append('field', `${filter.key}:${filter.value}`)
  }
  for (const filter of params.fieldText ?? []) {
    search.append('field_text', `${filter.key}:${filter.text}`)
  }
  for (const filter of params.refs ?? []) {
    search.append('ref', `${filter.kind}:${filter.value}`)
  }
  for (const filter of params.refText ?? []) {
    search.append('ref_text', `${filter.kind}:${filter.text}`)
  }
  if (params.limit !== undefined) search.set('limit', String(params.limit))
  if (params.offset !== undefined) search.set('offset', String(params.offset))
  const text = search.toString()
  return text ? `?${text}` : ''
}

/** Query for the item collection: `status` is repeatable, unlike the generic helper. */
export interface ItemQuery {
  statuses?: string[]
  decision?: string
  q?: string
  sort?: string
  order?: string
  limit?: number
  offset?: number
}

function itemsQuery(params: ItemQuery): string {
  const search = new URLSearchParams()
  for (const status of params.statuses ?? []) search.append('status', status)
  if (params.decision) search.set('decision', params.decision)
  if (params.q) search.set('q', params.q)
  if (params.sort) search.set('sort', params.sort)
  if (params.order) search.set('order', params.order)
  if (params.limit !== undefined) search.set('limit', String(params.limit))
  if (params.offset !== undefined) search.set('offset', String(params.offset))
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  workflows: (): Promise<WorkflowView[]> => request('/api/workflows'),
  version: (): Promise<VersionView> => request('/api/version'),
  session: (): Promise<SessionView> => request('/api/sessions'),
  sync: (workflow: string): Promise<SyncView | null> =>
    request(`/api/syncs${query({ workflow })}`),
  items: (route: string, params: ItemQuery = {}): Promise<ItemsPage> =>
    request(`/api/${route}${itemsQuery(params)}`),
  item: (route: string, key: string): Promise<ItemDetail> =>
    request(`/api/${route}/${encodeURIComponent(key)}`),
  history: (route: string, params: HistoryQuery = {}): Promise<HistoryPage> =>
    request(`/api/${route}/history${historyQuery(params)}`),
  historyItem: (route: string, key: string): Promise<ItemDetail> =>
    request(`/api/${route}/history/${encodeURIComponent(key)}`),
  patchFields: (
    route: string,
    key: string,
    changes: Record<string, string | null>,
  ): Promise<ItemDetail> =>
    request(`/api/${route}/${encodeURIComponent(key)}/field-values`, {
      method: 'PATCH',
      body: JSON.stringify(changes),
    }),
  decide: (
    route: string,
    key: string,
    decision: DecisionKind,
    reason?: string,
  ): Promise<ItemDetail> =>
    request(`/api/${route}/${encodeURIComponent(key)}/decisions`, {
      method: 'POST',
      body: JSON.stringify({ decision, reason: reason ?? null }),
    }),
  undoDecision: (route: string, key: string): Promise<ItemDetail> =>
    request(`/api/${route}/${encodeURIComponent(key)}/decisions`, { method: 'DELETE' }),
  submitJob: (route: string, key: string): Promise<JobView> =>
    request(`/api/${route}/${encodeURIComponent(key)}/jobs`, { method: 'POST' }),
  jobs: (params: JobQuery = {}): Promise<JobsPage> =>
    request(`/api/jobs${jobsQuery(params)}`),
  jobLogs: (id: number): Promise<JobLogs> => request(`/api/jobs/${id}/logs`),
  workers: (): Promise<QueueView> => request('/api/workers'),
  network: (): Promise<NetworkView> => request('/api/network'),
  updates: (): Promise<UpdateStatus> => request('/api/updates'),
  checkUpdate: (): Promise<UpdateStatus> =>
    request('/api/updates/checks', { method: 'POST' }),
  installUpdate: (): Promise<UpdateStatus> =>
    request('/api/updates/installations', { method: 'POST' }),
  login: (): Promise<SessionView> => request('/api/sessions', { method: 'POST' }),
  logout: (): Promise<void> => requestVoid('/api/sessions', { method: 'DELETE' }),
  requestSync: (workflow: string): Promise<{ status: string; workflow: string }> =>
    request(`/api/syncs${query({ workflow })}`, { method: 'POST' }),
  devTables: (): Promise<DevTablesView> => request('/api/dev/db/tables'),
  devQuery: (sql: string, limit = 500): Promise<DevQueryView> =>
    request('/api/dev/db/queries', {
      method: 'POST',
      body: JSON.stringify({ sql, limit }),
    }),
  devExport: (sql: string, format: 'csv' | 'xlsx'): Promise<Blob> =>
    requestBlob('/api/dev/db/exports', {
      method: 'POST',
      body: JSON.stringify({ sql, format }),
    }),
  devPurge: (scope: PurgeScope, dryRun: boolean): Promise<PurgeResult> =>
    request('/api/dev/db/purges', {
      method: 'POST',
      body: JSON.stringify({ scope, dryRun }),
    }),
}
