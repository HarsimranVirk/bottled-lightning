import { useCallback, useEffect, useState } from 'react'
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
import { api } from '../api'

const FIELDS = [
  { key: 'property_value', label: 'Property value' },
  { key: 'loan_amount', label: 'Loan amount' },
  { key: 'tenure', label: 'Tenure (months)', months: true },
  { key: 'emi', label: 'EMI & other fixed payments incl. HFFC Loan' },
]

// Numeric-only entry: draft holds pure digits; display adds Indian grouping
// (25,50,000) for amounts, plain digits for months.
const digitsOf = (raw) => String(raw ?? '').replace(/[^\d]/g, '')

function indianFormat(digits) {
  if (!digits) return ''
  return Number(digits).toLocaleString('en-IN')
}

// convert scraper hints like "20 Years" / "20.0 Yrs" / "240 M" into months
function tenureToMonths(raw) {
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

function prefillDisplay(field, raw) {
  if (field.months) return tenureToMonths(raw)
  return indianFormat(digitsOf(raw))
}

export default function Deck() {
  const [rows, setRows] = useState(null)
  const [tally, setTally] = useState({ accept: 0, skip: 0, pending: 0 })
  const [animClass, setAnimClass] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [draft, setDraft] = useState({}) // current card's editable params
  const [cardKey, setCardKey] = useState(0)
  const [sync, setSync] = useState({ status: 'idle', detail: '', result: null })

  const refresh = useCallback(async () => {
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
      setRows(all.filter((r) => r.decision === 'pending' || r.decision == null))
      setError(null)
      return all
    } catch (e) {
      setError(e.message)
      return []
    }
  }, [])

  useEffect(() => {
    void refresh() // initial load; async so state updates after await
  }, [refresh])

  // poll resync progress while it runs
  const pollSync = useCallback((startedAt) => {
    const tick = async () => {
      try {
        const s = await api.devResyncStatus()
        setSync(s)
        if (s.status === 'running') return setTimeout(tick, 2000)
        if (s.status === 'done') void refresh()
      } catch { /* transient */ }
    }
    void tick()
  }, [])

  const resync = () => {
    if (busy || animClass) return
    setSync({ status: 'running', detail: 'starting…', result: null })
    api.devResync()
      .then(() => pollSync())
      .catch((e) => {
        setError(e.status === 409 ? 'resync already running' : e.message)
        setSync({ status: 'idle', detail: '', result: null })
      })
  }

  const current = rows?.[0]
  const next = rows?.[1]
  const done = rows && rows.length === 0

  const advance = (to) => {
    setDraft({})
    setCardKey((k) => k + 1)
    setAnimClass(null)
    setBusy(false)
    setTally((t) => ({ ...t, [to]: t[to] + 1, pending: Math.max(0, t.pending - 1) }))
    setRows((prev) => prev?.filter((r) => r.value !== current?.value) ?? prev)
  }

  const decide = (row, decision) => {
    if (animClass || busy) return
    setAnimClass(decision === 'accept' ? 'deck-out-right' : 'deck-out-left')
    const param = (key, keyDigits) => {
      const d = digitsOf(draft[key])
      if (!d) return null
      return keyDigits ? indianFormat(d) : d
    }
    const payload = {
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
      .catch((e) => { setError(e.message); setAnimClass(null); setBusy(false) })
  }

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
          <Link href="#/runs" color="secondary">extraction status</Link>
          <Button appearance="outlined" disabled={busy || sync.status === 'running'} onClick={resync}>
            Resync queue
          </Button>
        </FlexLayout>
      </FlexLayout>

      {sync.status === 'running' && (
        <FlexLayout gap={1} align="center">
          <Spinner size="small" />
          <Text color="secondary">{sync.detail || 'comparing queue with Salesforce…'}</Text>
        </FlexLayout>
      )}
      {sync.status === 'done' && sync.result && (
        <FlexLayout gap={1} align="center">
          <StatusIndicator status={sync.result.new_in_sf.length || sync.result.missing_in_sf.length || sync.result.count_mismatch ? 'warning' : 'success'} />
          <Text>
            {sync.detail || `queue matches Salesforce (${sync.result.sf_count} deviations)`}
          </Text>
        </FlexLayout>
      )}
      {sync.status === 'failed' && (
        <FlexLayout gap={1} align="center">
          <StatusIndicator status="error" />
          <Text status="error">resync failed: {sync.detail}</Text>
        </FlexLayout>
      )}

      {error && (
        <FlexLayout gap={1} align="center">
          <StatusIndicator status="error" />
          <Text status="error">{error}</Text>
        </FlexLayout>
      )}

      {done && (
        <Card elevation="raised" accent="top">
          <CardContent>
            <StackLayout gap={1} style={{ textAlign: 'center', padding: 24 }}>
              <Text styleAs="h3">Deck complete 🎉</Text>
              <Text color="secondary">
                {tally.accept} accepted · {tally.skip} skipped. Decisions and
                accepted parameters are stored in data/app.db — run the update
                workflow when it ships.
              </Text>
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
                <Link href={current.record_url} target="_blank"
                  className="deck-title-link">
                  {current.value}
                </Link>
                <StatusIndicator status="info" />
              </FlexLayout>

              {current.opportunity_url && (
                <StackLayout gap={0.5}>
                  <Text color="secondary" styleAs="label">Pages to update</Text>
                  <Link href={current.opportunity_url} target="_blank">
                    🏢 Opportunity (linked record)
                  </Link>
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
                        ? (f.months ? draft[f.key] : indianFormat(draft[f.key]))
                        : prefillDisplay(f, current[f.key])}
                      onChange={(e) => setDraft({
                        ...draft,
                        [f.key]: digitsOf(e.target.value),
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
