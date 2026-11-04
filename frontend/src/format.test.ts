import { describe, expect, it } from 'vitest'

import { relativeTime, statusLabel, statusTone } from './format'

describe('statusTone', () => {
  it('maps lifecycle states to distinct tones', () => {
    expect(statusTone('completed')).toBe('success')
    expect(statusTone('needs_review')).toBe('danger')
    expect(statusTone('applying')).toBe('warning')
    expect(statusTone('ready')).toBe('info')
    expect(statusTone('closed')).toBe('neutral')
  })
})

describe('statusLabel', () => {
  it('prefers the workflow wording for terminal states', () => {
    expect(statusLabel('completed', { completed: 'Implemented' })).toBe('Implemented')
  })

  it('title-cases machine statuses otherwise', () => {
    expect(statusLabel('needs_review')).toBe('Needs Review')
  })
})

describe('relativeTime', () => {
  it('describes missing values and recent timestamps', () => {
    expect(relativeTime(null)).toBe('never')
    const now = new Date(Date.now() - 90_000).toISOString()
    expect(relativeTime(now)).toMatch(/min ago|s ago/)
  })
})
