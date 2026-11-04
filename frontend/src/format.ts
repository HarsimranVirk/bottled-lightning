/** Presentation helpers shared by the read-only screens. */

import type { FieldView } from './api'

export type Tone = 'info' | 'success' | 'warning' | 'danger' | 'neutral'

/** The value the operator sees: proposal, then extracted, then applied, else a dash. */
export function fieldValue(fields: Record<string, FieldView>, key: string): string {
  const field = fields[key]
  if (!field) return '—'
  return field.proposed ?? field.extracted ?? field.applied ?? '—'
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
