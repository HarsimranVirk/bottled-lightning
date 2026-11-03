import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  Input,
  StackLayout,
  FlexLayout,
  Text,
  StatusIndicator,
  Spinner,
} from '@salt-ds/core'
import { RunReportIcon } from '@salt-ds/icons'
import { api } from '../api'
import type { DeviationsResponse, IndicatorStatus, Job } from '../types'

interface JobStatusView {
  status: IndicatorStatus
  text: string
}

function statusForJob(job: Job | null | undefined): JobStatusView {
  if (!job) return { status: 'info', text: 'never run' }
  if (job.status === 'running') return { status: 'info', text: 'running…' }
  return { status: job.status === 'success' ? 'success' : 'error', text: job.detail ?? '' }
}

export default function DeviationsZ02() {
  const [data, setData] = useState<DeviationsResponse | null>(null)
  const [starting, setStarting] = useState(false)
  const [workers, setWorkers] = useState<number | null>(null)
  const [workerInput, setWorkerInput] = useState('')
  const [workerBusy, setWorkerBusy] = useState(false)
  const [logs, setLogs] = useState<string[]>([])
  const job = data?.job ?? null
  const jobId = job?.status === 'running' ? job.id : null

  const refresh = useCallback(async (): Promise<void> => {
    try {
      const d = await api.deviations()
      setData(d)
      // while a job is in flight, also pull its live row count
      if (d.job?.status === 'running') {
        const j = await api.job(d.job.id)
        setData({ ...d, job: j })
      }
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = setInterval(refresh, jobId ? 3000 : 12000)
    return () => clearInterval(id)
  }, [jobId, refresh])

  useEffect(() => {
    api.workers()
      .then((w) => { setWorkers(w.scrape_workers); setWorkerInput(String(w.scrape_workers)) })
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    const id = data?.job?.id
    if (!id) { setLogs([]); return }
    let cancelled = false
    const tick = async (): Promise<void> => {
      try {
        const r = await api.jobLogs(id)
        if (!cancelled) setLogs(r.logs)
      } catch { /* ignore */ }
    }
    void tick()
    const timer = setInterval(() => { void tick() }, 2000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [data?.job?.id])

  const run = async (): Promise<void> => {
    setStarting(true)
    try {
      if (data?.view?.id) await api.runView(data.view.id)
      await refresh()
    } catch {
      /* ignore */
    } finally {
      setStarting(false)
    }
  }

  const applyWorkers = async (): Promise<void> => {
    const n = Number(workerInput)
    if (!Number.isFinite(n)) return
    setWorkerBusy(true)
    try {
      const w = await api.setWorkers(n)
      setWorkers(w.scrape_workers)
      setWorkerInput(String(w.scrape_workers))
    } catch {
      /* ignore */
    } finally {
      setWorkerBusy(false)
    }
  }

  const running = job?.status === 'running'
  const jobStatus = statusForJob(job)
  const mismatch = job?.status === 'success'
    && job.header_total != null
    && job.extracted !== job.header_total

  return (
    <StackLayout gap={5}>
      <Card accent="left" elevation="raised">
        <CardHeader>
          <FlexLayout justify="space-between" align="center">
            <Text styleAs="h4"> Loan Deviations Z02 — extraction</Text>
            <FlexLayout gap={2} align="center">
              <Button
                sentiment="accented"
                appearance="solid"
                disabled={running || starting}
                onClick={run}
              >
                <RunReportIcon aria-hidden /> Run extraction
              </Button>
            </FlexLayout>
          </FlexLayout>
        </CardHeader>
        <CardContent>
          <StackLayout gap={3}>
            <FlexLayout gap={4} align="center" wrap>
              <FlexLayout gap={1} align="center">
                <Text styleAs="h2" style={{ marginBottom: 0 }}>
                  {data ? data.count : '…'}
                </Text>
                <Text color="secondary">deviations</Text>
              </FlexLayout>
              <FlexLayout gap={1} align="center">
                <StatusIndicator status={jobStatus.status} />
                <Text color={running ? 'primary' : 'secondary'}>
                  {running ? <>running<Spinner size="small" /></> : jobStatus.text}
                </Text>
              </FlexLayout>
            </FlexLayout>

            {mismatch && job && (
              <FlexLayout gap={1} align="center">
                <StatusIndicator status="warning" />
                <Text>
                  count mismatch: header shows {job.header_total},
                  extracted {job.extracted} — investigate before trusting
                </Text>
              </FlexLayout>
            )}
            {job?.status === 'success' && !mismatch && (
              <Text color="secondary" styleAs="label">
                cross-check ok: header {job.header_total} = extracted {job.extracted}
              </Text>
            )}

            <Text color="secondary" styleAs="label">
              view: {data ? `"${data.view.name}"` : '…'} · printed via the list view's
              Printable View (all rows at once); "Show more" pagination is clicked
              through in the fallback path
            </Text>
          </StackLayout>
        </CardContent>
      </Card>

      <Card elevation="raised">
        <CardHeader>
          <Text styleAs="h4">Dev mode — background workers</Text>
        </CardHeader>
        <CardContent>
          <StackLayout gap={2}>
            <Text color="secondary">
              Scrape workers currently: {workers ?? '…'} (used when picking
              descriptions from record pages).
            </Text>
            <FlexLayout gap={2} align="center">
              <Input
                inputMode="numeric"
                value={workerInput}
                onChange={(e) => setWorkerInput((e.target as HTMLInputElement).value)}
                style={{ width: 80 }}
              />
              <Button appearance="bordered" disabled={workerBusy} onClick={applyWorkers}>
                Apply
              </Button>
            </FlexLayout>
          </StackLayout>
        </CardContent>
      </Card>

      <Card elevation="raised">
        <CardHeader>
          <Text styleAs="h4">Dev mode — extraction logs</Text>
        </CardHeader>
        <CardContent>
          <div style={{ maxHeight: 320, overflowY: 'auto', background: '#111', color: '#0f0', padding: 8, fontFamily: 'monospace', fontSize: 11 }}>
            {logs.length === 0
              ? <Text color="secondary">no logs yet</Text>
              : logs.map((l, i) => <div key={i}>{l}</div>)}
          </div>
        </CardContent>
      </Card>
    </StackLayout>
  )
}
