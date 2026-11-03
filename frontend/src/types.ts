// Shared API/domain types mirrored from the FastAPI pydantic models and the
// shapes returned by app/store.py. Keep this the single source of truth for
// frontend data; components should never re-declare these shapes.

export type Decision = 'accept' | 'reject' | 'pending'

export type Route = 'home' | 'deviations-z02'

export type LoginStatus = 'idle' | 'running' | 'success' | 'failed'

export interface LoginState {
  status: LoginStatus
  detail: string
  in_progress?: boolean
}

export interface SessionEvent {
  id: number
  event: string
  detail: string | null
  created_at: string
}

export interface SessionInfo {
  org: string
  auth_snapshot_exists: boolean | null
  login: LoginState
  recent_events: SessionEvent[]
  last_login: string | null
  checked_at?: string
  snapshot_created_at?: string
  snapshot_org?: string
  snapshot_cookie_count?: number
  snapshot_age_seconds?: number
  snapshot_store?: 'sqlite' | 'legacy-file'
}

export interface StoredSessionInfo extends SessionInfo {
  checked_at: string
}

export interface ViewRecord {
  id: number
  name: string
  url: string
  pattern: string
  created_at: string
  latest_count?: number
  last_success?: string | null
}

export type JobStatus = 'running' | 'success' | 'failed'

export interface Job {
  id: number
  view_id: number
  status: JobStatus
  detail: string | null
  header_total: number | null
  extracted: number | null
  started_at: string
  finished_at: string | null
  view_name?: string
}

export interface LatestRow {
  value: string
  first_seen: string
  last_seen: string
}

export interface PageRef {
  seq: number
  name: string
  kind: string
  url: string
}

export interface DeviationRow extends LatestRow {
  approval_date: string | null
  description: string | null
  decision: Decision | null
  record_url: string | null
  page_refs: PageRef[]
  opportunity_url: string | null
  cl_contract_url: string | null
  collateral_url: string | null
  lms2_collateral_url: string | null
  lms2_cl_contract_url: string | null
  property_value: string | null
  loan_amount: string | null
  tenure: string | null
  emi: string | null
  requested_roi: string | null
  ideal_roi: string | null
  updated_roi: string | null
  requested_variance: string | null
}

export interface DeviationsResponse {
  view: ViewRecord & { latest_count: number }
  job: Job | null
  count: number
  rows: DeviationRow[]
}

export interface HistoryRow {
  id: number
  value: string
  sf_approval_date: string | null
  decided_at: string | null
  archived_at: string
  record_id: string | null
  record_url: string | null
  description: string | null
  property_value: string | null
  loan_amount: string | null
  tenure: string | null
  emi: string | null
  requested_roi: string | null
  ideal_roi: string | null
  updated_roi: string | null
  requested_variance: string | null
  opportunity_url: string | null
  cl_contract_url: string | null
  collateral_url: string | null
  lms2_collateral_url: string | null
  lms2_cl_contract_url: string | null
  page_refs_json: string | null
}

export interface HistoryResponse {
  rows: HistoryRow[]
  total: number
}

export type ResyncStatus = 'idle' | 'running' | 'done' | 'failed'

export interface ResyncQueue {
  pending: number
  accept: number
  reject: number
}

export interface ResyncResult {
  sf_count: number
  header_total: number | null
  count_mismatch: boolean
  db_count: number
  new_in_sf: string[]
  missing_in_sf: string[]
  added?: string[]
  removed?: string[]
  queue: ResyncQueue
}

export interface ResyncState {
  status: ResyncStatus
  detail: string
  result: ResyncResult | null
}

export interface DecisionPayload {
  decision: Decision
  property_value?: string | null
  loan_amount?: string | null
  tenure?: string | null
  emi?: string | null
}

export interface ViewPayload {
  name: string
  url: string
  pattern?: string
}

export interface StartLoginResponse {
  status: LoginStatus
  detail: string
  login_wait_seconds: number
}

export interface RunResponse {
  job_id: number
  view_id: number
}

export interface DeleteViewResponse {
  deleted: number
}

export interface ResultsResponse {
  view: string
  rows: LatestRow[]
}

export type IndicatorStatus = 'info' | 'success' | 'warning' | 'error'

export interface UpdateStatus {
  app_version: string
  current: string | null
  latest: string | null
  status: string
}
