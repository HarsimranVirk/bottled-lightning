/** The accept-and-submit sequence: ordering, no-op accepts and job rollback. */

import { describe, expect, it, vi } from 'vitest'

import { acceptAndSubmit } from './submit'
import type { AcceptanceActions } from './submit'

function actions(order: string[]): AcceptanceActions {
  return {
    patch: vi.fn(async () => {
      order.push('patch')
    }),
    decide: vi.fn(async () => {
      order.push('decide')
    }),
    submit: vi.fn(async () => {
      order.push('submit')
    }),
    undo: vi.fn(async () => {
      order.push('undo')
    }),
  }
}

describe('acceptAndSubmit', () => {
  it('patches, records the accept and queues the job when values exist', async () => {
    const order: string[] = []
    const calls = actions(order)
    const submitted = await acceptAndSubmit(
      'accept',
      { loan_amount: '14,50,000', tenure: null },
      calls,
    )
    expect(submitted).toBe(true)
    expect(order).toEqual(['patch', 'decide', 'submit'])
    expect(calls.undo).not.toHaveBeenCalled()
  })

  it('records only the decision when the card has no values', async () => {
    const order: string[] = []
    const calls = actions(order)
    const submitted = await acceptAndSubmit(
      'accept',
      { loan_amount: null, tenure: '  ' },
      calls,
    )
    expect(submitted).toBe(false)
    expect(order).toEqual(['decide'])
    expect(calls.patch).not.toHaveBeenCalled()
    expect(calls.submit).not.toHaveBeenCalled()
  })

  it('never queues a job for a skip', async () => {
    const order: string[] = []
    const calls = actions(order)
    const submitted = await acceptAndSubmit(
      'reject',
      { loan_amount: '14,50,000' },
      calls,
    )
    expect(submitted).toBe(false)
    expect(order).toEqual(['decide'])
    expect(calls.patch).not.toHaveBeenCalled()
    expect(calls.submit).not.toHaveBeenCalled()
  })

  it('undoes the accept when the job cannot be queued', async () => {
    const order: string[] = []
    const calls = actions(order)
    calls.submit = vi.fn(async () => {
      order.push('submit')
      throw new Error('job failed')
    })
    await expect(
      acceptAndSubmit('accept', { loan_amount: '14,50,000' }, calls),
    ).rejects.toThrow('job failed')
    expect(order).toEqual(['patch', 'decide', 'submit', 'undo'])
  })

  it('keeps the original job error when undo also fails', async () => {
    const order: string[] = []
    const calls = actions(order)
    calls.submit = vi.fn(async () => {
      throw new Error('job failed')
    })
    calls.undo = vi.fn(async () => {
      throw new Error('undo failed')
    })
    await expect(
      acceptAndSubmit('accept', { loan_amount: '14,50,000' }, calls),
    ).rejects.toThrow('job failed')
  })
})
