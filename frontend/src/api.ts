import type {
  DecisionPayload,
  DeleteViewResponse,
  DeviationsResponse,
  HistoryResponse,
  Job,
  ResultsResponse,
  ResyncState,
  RunResponse,
  SessionInfo,
  StartLoginResponse,
  UpdateStatus,
  ViewPayload,
  ViewRecord,
} from './types'

const API = '/api'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export function errorStatus(error: unknown): number | undefined {
  return error instanceof ApiError ? error.status : undefined
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body: unknown = await res.clone().json()
      if (body && typeof body === 'object' && 'detail' in body) {
        detail = String((body as { detail: unknown }).detail)
      } else {
        detail = JSON.stringify(body)
      }
    } catch { /* non-JSON error body */ }
    throw new ApiError(detail, res.status)
  }
  return (res.status === 204 ? null : await res.json()) as T
}

const get = <T,>(path: string): Promise<T> =>
  fetch(`${API}${path}`).then((res) => json<T>(res))

const post = <T,>(path: string, body?: unknown): Promise<T> =>
  fetch(`${API}${path}`, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }).then((res) => json<T>(res))

const patch = <T,>(path: string, body?: unknown): Promise<T> =>
  fetch(`${API}${path}`, {
    method: 'PATCH',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }).then((res) => json<T>(res))

const del = <T,>(path: string): Promise<T> =>
  fetch(`${API}${path}`, { method: 'DELETE' }).then((res) => json<T>(res))

export const api = {
  listViews: () => get<ViewRecord[]>('/views'),
  addView: (body: ViewPayload) => post<ViewRecord>('/views', body),
  deleteView: (id: number) => del<DeleteViewResponse>(`/views/${id}`),
  runView: (id: number) => post<RunResponse>(`/views/${id}/jobs`),
  listJobs: () => get<Job[]>('/jobs'),
  job: (id: number) => get<Job>(`/jobs/${id}`),
  jobLogs: (id: number) => get<{ job_id: number; logs: string[] }>(`/jobs/${id}/logs`),
  results: (viewId: number) => get<ResultsResponse>(`/views/${viewId}/results`),
  sessionStatus: () => get<SessionInfo>('/sessions'),
  startLogin: (reset = false) => post<StartLoginResponse>('/sessions', { reset }),
  resetSession: () => del<{ status: string }>('/sessions'),
  deviations: (decision?: string) =>
    get<DeviationsResponse>(`/deviations${decision ? `?decision=${encodeURIComponent(decision)}` : ''}`),
  history: (params?: Record<string, string | number>) => {
    const qs = params
      ? '?' + Object.entries(params).filter(([, v]) => v !== '' && v != null)
          .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join('&')
      : ''
    return get<HistoryResponse>(`/deviations/history${qs}`)
  },
  decide: (value: string, decision: DecisionPayload) =>
    patch<Record<string, unknown>>(
      `/deviations/${encodeURIComponent(value)}`, decision),
  devResync: () => post<{ status: string }>('/syncs'),
  devResyncStatus: () => get<ResyncState>('/syncs'),
  workers: () => get<{ scrape_workers: number }>('/workers'),
  setWorkers: (count: number) =>
    patch<{ scrape_workers: number }>('/workers', { count }),
  updateStatus: () => get<UpdateStatus>('/updates'),
  updateCheck: () => post<UpdateStatus>('/updates/checks'),
  updateApply: () => post<Record<string, unknown>>('/updates/installations'),
}
