import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { ItemDetail } from '../api'
import { ItemDrawer } from './ItemDrawer'

const base: ItemDetail = {
  key: 'Deviation-1-1',
  status: 'ready',
  present: true,
  epoch: 1,
  recordUrl: null,
  approvedAt: null,
  reason: null,
  fields: {
    loan_amount: {
      extracted: '13,00,000',
      lastSynced: '13,00,000',
      proposed: null,
      applied: null,
      status: 'extracted',
    },
  },
  decision: null,
  activeJob: null,
  attributes: { product_type: 'Home Loan', description: 'LA-13,00,000' },
  refs: [{ kind: 'opportunity', name: 'Opp', url: 'https://example/opp', state: 'found' }],
  edits: [{ field: 'tenure', oldValue: null, newValue: '240', at: '2026-11-04T18:05:00Z' }],
  decisions: [],
  extractionRetryable: false,
  extractionJob: null,
}

const fields = [
  { key: 'loan_amount', label: 'Loan Amount', valueType: 'amount', required: false, targets: ['cl_contract'] },
]

describe('ItemDrawer', () => {
  it('shows the found object and marks the missing ones', () => {
    render(
      <ItemDrawer
        detail={base}
        fields={fields}
        refKinds={['opportunity', 'cl_contract']}
        terminalLabels={{}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('Opp')).toBeInTheDocument()
    expect(screen.getByText('not found')).toBeInTheDocument()
  })

  it('renders editable values and recorded history', () => {
    render(
      <ItemDrawer detail={base} fields={fields} refKinds={[]} terminalLabels={{}} onClose={() => {}} />,
    )
    expect(screen.getAllByText('13,00,000').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/240/).length).toBeGreaterThan(0)
  })

  it('shows the decision and offers undo', () => {
    render(
      <ItemDrawer
        detail={{
          ...base,
          decision: { decision: 'reject', reason: 'EMI mismatch', at: '2026-11-04T18:20:00Z' },
          decisions: [{ decision: 'reject', reason: 'EMI mismatch', at: '2026-11-04T18:20:00Z' }],
        }}
        fields={fields}
        refKinds={[]}
        terminalLabels={{}}
        onClose={() => {}}
        onUndoDecision={() => {}}
      />,
    )
    expect(screen.getAllByText(/EMI mismatch/).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Undo decision' })).toBeInTheDocument()
  })

  it('explains why an item is not actionable', () => {
    render(
      <ItemDrawer
        detail={{ ...base, status: 'needs_review', reason: 'submission failed' }}
        fields={fields}
        refKinds={[]}
        terminalLabels={{}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('submission failed')).toBeInTheDocument()
  })
})
