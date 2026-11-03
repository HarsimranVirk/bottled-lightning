import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  StackLayout,
  FlexLayout,
  Text,
  Input,
  Table,
  TableContainer,
  THead,
  TBody,
  TR,
  TD,
  TH,
  Spinner,
} from '@salt-ds/core'
import { api, errorMessage } from '../api'
import type { HistoryResponse, HistoryRow } from '../types'

const PAGE_SIZE = 25

const COLUMNS: { key: keyof HistoryRow; label: string }[] = [
  { key: 'value', label: 'Deviation' },
  { key: 'sf_approval_date', label: 'SF Approval date' },
  { key: 'decided_at', label: 'Decided at' },
  { key: 'record_id', label: 'Record ID' },
  { key: 'description', label: 'Description' },
  { key: 'property_value', label: 'Property value' },
  { key: 'loan_amount', label: 'Loan amount' },
  { key: 'tenure', label: 'Tenure' },
  { key: 'emi', label: 'EMI' },
  { key: 'requested_roi', label: 'Requested ROI' },
  { key: 'ideal_roi', label: 'Ideal ROI' },
  { key: 'updated_roi', label: 'Updated ROI' },
  { key: 'requested_variance', label: 'Variance' },
  { key: 'opportunity_url', label: 'Opportunity' },
  { key: 'cl_contract_url', label: 'CL Contract' },
  { key: 'collateral_url', label: 'Collateral' },
  { key: 'lms2_collateral_url', label: 'LMS2 Collateral' },
  { key: 'lms2_cl_contract_url', label: 'LMS2 CL Contract' },
  { key: 'archived_at', label: 'Archived at' },
]

export default function History() {
  const [data, setData] = useState<HistoryResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [limit] = useState(PAGE_SIZE)
  const [filters, setFilters] = useState<Record<string, string>>({})

  const load = useCallback(async (): Promise<void> => {
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string | number> = { limit, offset }
      for (const [k, v] of Object.entries(filters)) {
        if (v.trim() !== '') params[k] = v.trim()
      }
      const d = await api.history(params)
      setData(d)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [filters, limit, offset])

  useEffect(() => {
    void load()
  }, [load])

  const setFilter = (key: string, val: string): void => {
    setFilters((prev) => ({ ...prev, [key]: val }))
    setOffset(0)
  }

  const total = data?.total ?? 0
  const rows = data?.rows ?? []
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + limit, total)

  return (
    <StackLayout gap={3}>
      <Card accent="left" elevation="raised">
        <CardHeader>
          <FlexLayout justify="space-between" align="center">
            <Text styleAs="h4">Audit history — accepted deviations</Text>
            <Button appearance="bordered" disabled={loading} onClick={() => { void load() }}>
              Refresh
            </Button>
          </FlexLayout>
        </CardHeader>
        <CardContent>
          {error && <Text color="error">{error}</Text>}
          {loading && rows.length === 0 && (
            <FlexLayout gap={1} align="center">
              <Spinner size="small" />
              <Text color="secondary">loading…</Text>
            </FlexLayout>
          )}
          <div style={{ overflowX: 'auto' }}>
            <TableContainer>
            <Table>
              <THead>
                <TR>
                  {COLUMNS.map((c) => (
                    <TH key={c.key}>
                      <StackLayout gap={0.5}>
                        <Text styleAs="label" color="secondary">{c.label}</Text>
                        <Input
                          value={filters[c.key] ?? ''}
                          onChange={(e) => setFilter(c.key, (e.target as HTMLInputElement).value)}
                          placeholder="filter…"
                        />
                      </StackLayout>
                    </TH>
                  ))}
                </TR>
              </THead>
              <TBody>
                {rows.map((r) => (
                  <TR key={r.id}>
                    {COLUMNS.map((c) => (
                      <TD key={c.key}>
                        <Text style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
                          {String(r[c.key] ?? '—')}
                        </Text>
                      </TD>
                    ))}
                  </TR>
                ))}
                {rows.length === 0 && !loading && (
                  <TR>
                    <TD colSpan={COLUMNS.length}>
                      <Text color="secondary">no archived deviations yet</Text>
                    </TD>
                  </TR>
                )}
              </TBody>
            </Table>
            </TableContainer>
          </div>

          <FlexLayout justify="space-between" align="center" style={{ marginTop: 8 }}>
            <Text color="secondary" styleAs="label">
              {total === 0 ? '0 rows' : `${from}–${to} of ${total}`}
            </Text>
            <FlexLayout gap={2}>
              <Button appearance="bordered" disabled={offset === 0 || loading}
                onClick={() => setOffset((o) => Math.max(0, o - limit))}>
                Prev
              </Button>
              <Button appearance="bordered" disabled={to >= total || loading}
                onClick={() => setOffset((o) => o + limit)}>
                Next
              </Button>
            </FlexLayout>
          </FlexLayout>
        </CardContent>
      </Card>
    </StackLayout>
  )
}