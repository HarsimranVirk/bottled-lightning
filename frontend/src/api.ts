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
  kind?: string
  status?: string
  phase?: string
  item?: string
  id?: string
  error?: string
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
              : key
    search.set(wire, String(value))
  }
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
  login: (): Promise<SessionView> => request('/api/sessions', { method: 'POST' }),
  logout: (): Promise<void> => requestVoid('/api/sessions', { method: 'DELETE' }),
  requestSync: (workflow: string): Promise<{ status: string; workflow: string }> =>
    request(`/api/syncs${query({ workflow })}`, { method: 'POST' }),
}
