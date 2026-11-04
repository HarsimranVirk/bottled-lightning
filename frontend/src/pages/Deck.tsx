import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Button,
  Card,
  CardContent,
  Input,
  Link,
  StackLayout,
  FlexLayout,
  Text,
  StatusIndicator,
  Spinner,
} from '@salt-ds/core'
import { SuccessIcon, DoubleChevronRightIcon } from '@salt-ds/icons'
import { api, errorMessage, errorStatus } from '../api'
import type { DecisionPayload, DeviationRow, ResyncState } from '../types'

type FieldKey = 'property_value' | 'loan_amount' | 'tenure' | 'emi'

interface Field {
  key: FieldKey
  label: string
  months?: boolean
}

const FIELDS: readonly Field[] = [
  { key: 'property_value', label: 'Property value' },
  { key: 'loan_amount', label: 'Loan amount' },
  { key: 'tenure', label: 'Tenure (months)', months: true },
  { key: 'emi', label: 'EMI & other fixed payments incl. HFFC Loan' },
]

type Draft = Partial<Record<FieldKey, string>>

// Numeric-only entry: draft holds pure digits; display adds Indian grouping
// (25,50,000) for amounts, plain digits for months.
const digitsOf = (raw: unknown): string => String(raw ?? '').replace(/[^\d]/g, '')

function indianFormat(digits: string): string {
  if (!digits) return ''
  return Number(digits).toLocaleString('en-IN')
}

// convert scraper hints like "20 Years" / "20.0 Yrs" / "240 M" into months
function tenureToMonths(raw: string | null | undefined): string {
  if (raw == null) return ''
  const m = String(raw).match(/([\d.]+)\s*(years?|yrs?|months?|m)?/i)
  if (!m) return ''
  const n = parseFloat(m[1])
  if (isNaN(n)) return ''
  const unit = (m[2] || '').toLowerCase()
  if (unit.startsWith('year') || unit === 'yrs' || unit === 'yr') {
    return String(Math.round(n * 12))
  }
  return String(Math.round(n))
}

function prefillDisplay(field: Field, raw: string | null | undefined): string {
  if (field.months) return tenureToMonths(raw)
  return indianFormat(digitsOf(raw))
}

interface Tally {
  accept: number
  skip: number
  pending: number
}

const EMPTY_SYNC: ResyncState = {
  status: 'idle',
  detail: '',
  result: null,
  busy: false,
  cycle: 0,
  interval_seconds: 0,
  last_run_at: null,
  job_running: false,
}

export default function Deck() {
  const [rows, setRows] = useState<DeviationRow[] | null>(null)
  const [tally, setTally] = useState<Tally>({ accept: 0, skip: 0, pending: 0 })
  const [animClass, setAnimClass] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft>({}) // current card's editable params
  const [cardKey, setCardKey] = useState(0)
  const [sync, setSync] = useState<ResyncState>(EMPTY_SYNC)
  const [replay, setReplay] = useState(false)

  const refresh = useCallback(async (): Promise<DeviationRow[]> => {
    try {
      const d = await api.deviations()
      const all = d.rows ?? []
      const rejects = all.filter((r) => r.decision === 'reject').length
      const accepts = all.filter((r) => r.decision === 'accept').length
      setTally({
        accept: accepts,
        skip: rejects,
        pending: all.length - accepts - rejects,
      })
      const visible = replay
         ? all.filter((r) => r.decision === 'pending' || r.decision === 'reject' || r.decision == null)
         : all.filter((r) => r.decision === 'pending' || r.decision == null)
       setRows(visible)
      setError(null)
      return all
    } catch (e) {
      setError(errorMessage(e))
      return []
    }
  }, [replay])

  useEffect(() => {
    void refresh() // initial load; async so state updates after await
  }, [refresh])

  // the backend resyncs on a loop; poll it and refresh when the queue changed
  const cycleRef = useRef(0)
  const jobRunningRef = useRef(false)
  useEffect(() => {
    let cancelled = false
    const tick = async (): Promise<void> => {
      try {
        const s = await api.devResyncStatus()
        if (cancelled) return
        setSync(s)
        if (s.cycle !== cycleRef.current) {
          cycleRef.current = s.cycle
          const r = s.result
          if (r && ((r.added?.length ?? 0) > 0 || (r.removed?.length ?? 0) > 0)) {
            void refresh()
          }
        }
        // details were filled in by a finished extraction job
        if (jobRunningRef.current && !s.job_running) void refresh()
        jobRunningRef.current = s.job_running
      } catch { /* transient */ }
      if (!cancelled) setTimeout(() => { void tick() }, 5000)
    }
    void tick()
    return () => { cancelled = true }
  }, [refresh])

  const resync = (): void => {
    if (busy || animClass) return
    setSync((s) => ({ ...s, busy: true, detail: 'starting…' }))
    api.devResync()
      .catch((e: unknown) => {
        setError(errorStatus(e) === 409 ? 'resync already running' : errorMessage(e))
        setSync((s) => ({ ...s, busy: false }))
      })
  }

  const current = rows?.[0]
  const next = rows?.[1]
  const done = rows && rows.length === 0

  const advance = (to: 'accept' | 'reject'): void => {
    setDraft({})
    setCardKey((k) => k + 1)
    setAnimClass(null)
    setBusy(false)
    const tallyKey = to === 'accept' ? 'accept' : 'skip'
    setTally((t) => ({
      ...t,
      [tallyKey]: t[tallyKey] + 1,
      pending: Math.max(0, t.pending - 1),
    }))
    setRows((prev) => prev?.filter((r) => r.value !== current?.value) ?? prev)
  }

  const decide = (row: DeviationRow, decision: 'accept' | 'reject'): void => {
    if (animClass || busy) return
    setAnimClass(decision === 'accept' ? 'deck-out-right' : 'deck-out-left')
    const param = (key: FieldKey, keyDigits: boolean): string | null => {
      const d = digitsOf(draft[key])
      if (!d) return null
      return keyDigits ? indianFormat(d) : d
    }
    const payload: DecisionPayload = {
      decision,
      ...(decision === 'accept' ? {
        property_value: param('property_value', true),
        loan_amount: param('loan_amount', true),
        tenure: param('tenure', false),
        emi: param('emi', true),
      } : {}),
    }
    setBusy(true)
    api.decide(row.value, payload)
      .then(() => setTimeout(
        () => { advance(decision); setTimeout(refresh, 1500) }, 420))
      .catch((e: unknown) => {
        setError(errorMessage(e))
        setAnimClass(null)
        setBusy(false)
      })
  }

  const syncResult = sync.result

  return (
    <StackLayout gap={4}>
      <FlexLayout justify="space-between" align="center">
        <FlexLayout gap={3} align="center">
          <FlexLayout gap={1} align="center">
            <StatusIndicator status="success" />
            <Text>{tally.accept} accepted</Text>
          </FlexLayout>
          <FlexLayout gap={1} align="center">
            <StatusIndicator status="error" />
            <Text>{tally.skip} skipped</Text>
          </FlexLayout>
          <FlexLayout gap={1} align="center">
            <StatusIndicator status="info" />
            <Text>{tally.pending} to review</Text>
          </FlexLayout>
        </FlexLayout>
        <FlexLayout gap={2} align="center">
          <Button appearance="bordered" disabled={busy || sync.busy} onClick={resync}>
            Sync now
          </Button>
          <Button appearance="bordered" disabled={busy} onClick={() => { void refresh() }}>
            Refresh
          </Button>
        </FlexLayout>
      </FlexLayout>

      {sync.busy && (
        <FlexLayout gap={1} align="center">
          <Spinner size="small" />
          <Text color="secondary">{sync.detail || 'comparing queue with Salesforce…'}</Text>
        </FlexLayout>
      )}
      {!sync.busy && sync.status === 'done' && syncResult && (
        <FlexLayout gap={1} align="center">
          <StatusIndicator status={syncResult.new_in_sf.length || syncResult.missing_in_sf.length || syncResult.count_mismatch ? 'warning' : 'success'} />
          <Text>
            {sync.detail || `queue matches Salesforce (${syncResult.sf_count} deviations)`}
            {sync.interval_seconds > 0 ? ` · auto-syncs every ${sync.interval_seconds}s` : ''}
          </Text>
        </FlexLayout>
      )}
      {!sync.busy && sync.status === 'failed' && (
        <FlexLayout gap={1} align="center">
          <StatusIndicator status="error" />
          <Text color="error">resync failed: {sync.detail}</Text>
        </FlexLayout>
      )}

      {error && (
        <FlexLayout gap={1} align="center">
          <StatusIndicator status="error" />
          <Text color="error">{error}</Text>
        </FlexLayout>
      )}

      {done && (
        <Card elevation="raised" accent="top">
          <CardContent>
            <StackLayout gap={1} style={{ textAlign: 'center', padding: 24 }}>
              <Text styleAs="h3">{replay ? 'Replay complete 🎉' : 'Deck complete 🎉'}</Text>
              <Text color="secondary">
                {tally.accept} accepted · {tally.skip} skipped. Decisions and
                accepted parameters are stored in data/app.db — run the update
                workflow when it ships.
              </Text>
              <FlexLayout gap={2} justify="center" style={{ marginTop: 12 }}>
                {!replay && tally.skip > 0 && (
                  <Button appearance="bordered" onClick={async () => {
                    // move skipped (rejected) cards back to review (pending)
                    try {
                      const d = await api.deviations()
                      const skipped = (d.rows ?? []).filter((r) => r.decision === 'reject')
                      await Promise.all(skipped.map((r) => api.decide(r.value, { decision: 'pending' })))
                    } catch { /* ignore */ }
                    setReplay(true)
                    void refresh()
                  }}>
                    Replay skipped ({tally.skip})
                  </Button>
                )}
                {replay && (
                  <Button appearance="bordered" onClick={() => { setReplay(false); void refresh() }}>
                    Exit replay
                  </Button>
                )}
                <Button appearance="bordered" onClick={() => void refresh()}>
                  Refresh
                </Button>
              </FlexLayout>
            </StackLayout>
          </CardContent>
        </Card>
      )}

      {!rows && (
        <FlexLayout justify="center" gap={1} align="center">
          <Spinner size="medium" />
          <Text color="secondary">shuffling the deck…</Text>
        </FlexLayout>
      )}

      {current && (
        <Card elevation="raised" className="deck-stack" key={cardKey}>
          <CardContent>
            <StackLayout gap={2} className={`deck-card ${animClass ?? ''}`}>
              <FlexLayout justify="space-between" align="center">
                <Link href={current.record_url ?? undefined} target="_blank"
                  className="deck-title-link">
                  {current.value}
                </Link>
                <StatusIndicator status="info" />
              </FlexLayout>
              {current.approval_date && (
                <Text color="secondary" styleAs="label">
                  SF approval date: {current.approval_date}
                </Text>
              )}

              {((current.page_refs && current.page_refs.length > 0) ||
                current.opportunity_url || current.cl_contract_url) && (
                <StackLayout gap={0.5}>
                  <Text color="secondary" styleAs="label">Pages to update</Text>
                  {(current.page_refs ?? [])
                    .filter((ref) => ['opportunity', 'cl_contract', 'collateral',
                      'lms2_collateral', 'lms2_cl_contract'].includes(ref.kind))
                    .map((ref) => (
                    <FlexLayout key={ref.seq} gap={1} align="center">
                      <Text styleAs="label" color="secondary" style={{ minWidth: 110, fontSize: 11 }}>
                        {ref.kind === 'opportunity' ? 'Opportunity' :
                         ref.kind === 'cl_contract' ? 'CL Contract' :
                         ref.kind === 'collateral' ? 'Collateral' :
                         ref.kind === 'lms2_collateral' ? 'LMS2 Collateral' :
                         ref.kind === 'lms2_cl_contract' ? 'LMS2 CL Contract' :
                         ref.kind}
                      </Text>
                      <Link href={ref.url} target="_blank">
                        {ref.name}
                      </Link>
                    </FlexLayout>
                  ))}
                </StackLayout>
              )}

              <Text color="secondary" styleAs="label">
                Loan Deviation Description — read it, raw is truth
              </Text>
              <div className="deck-description">
                {current.description
                  ? <Text styleAs="code" style={{ fontSize: 12, whiteSpace: 'pre-wrap', display: 'block' }}>
                      {current.description}
                    </Text>
                  : <Text color="secondary">
                      no description picked yet — run an extraction first
                    </Text>}
              </div>

              <Text color="secondary" styleAs="label">
                Housing Loan Deviation Details
              </Text>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                <StackLayout gap={0}>
                  <Text color="secondary" styleAs="label">Requested ROI</Text>
                  <Text>{current.requested_roi ?? '—'}</Text>
                </StackLayout>
                <StackLayout gap={0}>
                  <Text color="secondary" styleAs="label">Ideal ROI</Text>
                  <Text>{current.ideal_roi ?? '—'}</Text>
                </StackLayout>
                <StackLayout gap={0}>
                  <Text color="secondary" styleAs="label">Updated ROI (in LMS)</Text>
                  <Text>{current.updated_roi ?? '—'}</Text>
                </StackLayout>
                <StackLayout gap={0}>
                  <Text color="secondary" styleAs="label">Requested Variance</Text>
                  <Text>{current.requested_variance ?? '—'}</Text>
                </StackLayout>
              </div>

              <Text color="secondary" styleAs="label">
                New loan parameters to populate — prefilled where the parser
                could read the description; correct anything it got wrong:
              </Text>
              <StackLayout gap={2}>
                {FIELDS.map((f) => (
                  <FlexLayout key={f.key} gap={2} align="center">
                    <Text styleAs="label" color="secondary" style={{ width: 130 }}>
                      {f.label}
                    </Text>
                    <Input
                      inputMode="numeric"
                      value={draft[f.key] != null
                        ? (f.months ? draft[f.key] : indianFormat(draft[f.key] ?? ''))
                        : prefillDisplay(f, current[f.key])}
                      onChange={(e) => setDraft({
                        ...draft,
                        [f.key]: digitsOf((e.target as HTMLInputElement).value),
                      })}
                      placeholder={f.months ? 'months' : '—'}
                    />
                  </FlexLayout>
                ))}
              </StackLayout>
            </StackLayout>
          </CardContent>
        </Card>
      )}

      {current && (
        <FlexLayout justify="center" gap={3} align="center">
          <Button
            appearance="solid"
            disabled={busy}
            onClick={() => decide(current, 'reject')}
            style={{ minWidth: 150 }}
          >
            <DoubleChevronRightIcon aria-hidden /> Skip
          </Button>
          <Button
            sentiment="accented"
            appearance="solid"
            disabled={busy}
            onClick={() => decide(current, 'accept')}
            style={{ minWidth: 150 }}
          >
            <SuccessIcon aria-hidden /> Accept
          </Button>
        </FlexLayout>
      )}

      {next && (
        <Text color="secondary" styleAs="label" style={{ textAlign: 'center' }}>
          next up: {next.value}
        </Text>
      )}
    </StackLayout>
  )
}
