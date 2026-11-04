import { describe, expect, it } from 'vitest'

import { readDetail } from './api'

describe('readDetail', () => {
  it('reads the documented structured error', () => {
    expect(readDetail(422, { detail: { code: 'invalid_value', message: 'not an amount' } })).toEqual({
      message: 'not an amount',
      code: 'invalid_value',
    })
  })

  it('accepts a plain string detail', () => {
    expect(readDetail(404, { detail: 'unknown item' })).toEqual({ message: 'unknown item', code: null })
  })

  it('falls back for unknown bodies', () => {
    expect(readDetail(500, null)).toEqual({ message: 'request failed (500)', code: null })
    expect(readDetail(502, 'nope')).toEqual({ message: 'request failed (502)', code: null })
  })
})
