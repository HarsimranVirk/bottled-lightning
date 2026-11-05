/** Presentation helpers shared by the read-only screens. */

import type { FieldView, ItemRow, WorkflowFieldView } from './api'

export type Tone = 'info' | 'success' | 'warning' | 'danger' | 'neutral'

/**
 * The value the operator sees: proposal, then extracted, then applied, else blank.
 *
 * ``lastSynced`` is deliberately never used here. The current Salesforce value is not a
 * prefill and must not be shown as a hint; an unchanged field starts blank in the edit
 * form, and the operator decides whether to supply a value. The read-only views also
 * leave the value blank rather than rendering a dash, so there is no visual hint either.
 */
export function fieldValue(fields: Record<string, FieldView>, key: string): string {
  const field = fields[key]
  if (!field) return ''
  return field.proposed ?? field.extracted ?? field.applied ?? ''
}

/** Colour tone for an item status. The word is always rendered too (FR-9.10). */
export function statusTone(status: string): Tone {
  switch (status) {
    case 'ready':
      return 'info'
    case 'editing':
      return 'info'
    case 'submitting':
    case 'applying':
    case 'validating':
    case 'executing':
      return 'warning'
    case 'needs_review':
      return 'danger'
    case 'completed':
      return 'success'
    case 'closed':
      return 'neutral'
    case 'skipped':
      return 'warning'
    case 'absent_pending':
      return 'warning'
    default:
      return 'neutral'
  }
}

/** Human label for a status, preferring the workflow's terminal wording. */
export function statusLabel(status: string, labels?: Record<string, string>): string {
  const custom = labels?.[status]
  if (custom) return custom
  return status.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

/** Short relative age, e.g. "3 min ago". */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 'unknown'
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

/** Local wall-clock time, e.g. "6:46 pm". */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}


/** Resolve a record href against the Salesforce list URL (old rows stored it relative). */
export function absoluteUrl(href: string, base: string): string {
  try {
    return new URL(href, base).toString()
  } catch {
    return href
  }
}

/** Digits only; the legacy deck edits amounts as pure digits and formats for display. */
export function digitsOf(raw: string | null | undefined): string {
  return String(raw ?? '').replace(/[^\d]/g, '')
}

/** Indian digit grouping for an amount, e.g. 2550000 -> "25,50,000". */
export function indianFormat(digits: string): string {
  if (!digits) return ''
  return Number(digits).toLocaleString('en-IN')
}

/**
 * Convert parser hints like "20 Years" / "20.0 Yrs" / "240 M" into months.
 *
 * This is the legacy deck's rule, kept verbatim: a bare number is already months, and
 * a decimal without a unit is rounded (10.0 -> 10), never guessed as years.
 */
export function tenureToMonths(raw: string | null | undefined): string {
  if (raw == null) return ''
  const match = String(raw).match(/([\d.]+)\s*(years?|yrs?|months?|m)?/i)
  if (!match) return ''
  const value = Number.parseFloat(match[1])
  if (Number.isNaN(value)) return ''
  const unit = (match[2] ?? '').toLowerCase()
  if (unit.startsWith('year') || unit === 'yrs' || unit === 'yr') {
    return String(Math.round(value * 12))
  }
  return String(Math.round(value))
}

/**
 * The card's draft starts from the proposed/extracted/applied value, never from the
 * current SF value (``lastSynced``). A field with no proposal or prefill starts blank.
 */
export function draftFor(field: WorkflowFieldView, row: ItemRow): string {
  const raw = fieldValue(row.fields, field.key)
  if (!raw) return ''
  if (field.valueType === 'amount') return digitsOf(raw)
  if (field.valueType === 'months') return tenureToMonths(raw)
  return raw
}

/** Read-only display for an editable value: amounts grouped, months plain, blank if none. */
export function displayValue(field: WorkflowFieldView, raw: string): string {
  if (!raw) return ''
  return field.valueType === 'amount' ? indianFormat(digitsOf(raw)) : raw
}

/** What the input shows: amounts are grouped, tenure stays plain digits. */
export function draftDisplay(field: WorkflowFieldView, value: string): string {
  return field.valueType === 'amount' ? indianFormat(value) : value
}

/**
 * Whether a PATCH body contains at least one non-empty value.
 *
 * Accept uses this to decide whether there is anything to submit: a card with every
 * field blank records the decision only, while any real value queues the update.
 */
export function hasChanges(changes: Record<string, string | null>): boolean {
  return Object.values(changes).some(
    (value) => value !== null && value.trim() !== '',
  )
}

/**
 * Build the PATCH body for an accept: every catalogue field as its cleaned display
 * value, or null when the operator left it empty.
 */
export function changesFor(
  fields: WorkflowFieldView[],
  draft: Record<string, string>,
): Record<string, string | null> {
  const changes: Record<string, string | null> = {}
  for (const field of fields) {
    const value = (draft[field.key] ?? '').trim()
    if (!value) {
      changes[field.key] = null
    } else if (field.valueType === 'amount') {
      changes[field.key] = indianFormat(digitsOf(value))
    } else {
      changes[field.key] = value
    }
  }
  return changes
}

/** The legacy card's field order; unknown catalogue fields come after it. */
export function orderedFields(fields: WorkflowFieldView[]): WorkflowFieldView[] {
  const order = ['property_value', 'loan_amount', 'tenure', 'emi_incl_hffc']
  const rank = (key: string): number => {
    const index = order.indexOf(key)
    return index === -1 ? order.length : index
  }
  return [...fields].sort((left, right) => rank(left.key) - rank(right.key))
}


/** Human duration from milliseconds: "340ms", "4.2s", "1m 5s", "2h 3m". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  if (minutes < 60) return `${minutes}m ${rest}s`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}

/** Date + local time, e.g. "04 Nov, 9:40 pm". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString([], {
    day: '2-digit',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  })
}
