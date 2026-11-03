import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  StackLayout,
  FlexLayout,
  Text,
  Link,
  StatusIndicator,
  Spinner,
} from '@salt-ds/core'
import { RunReportIcon, DownloadIcon } from '@salt-ds/icons'
import { api } from '../api'

function statusForJob(job) {
  if (!job) return { status: 'info', text: 'never run' }
  if (job.status === 'running') return { status: 'info', text: 'running…' }
  if (job.status === 'success') return { status: 'success', text: job.detail }
  return { status: 'error', text: job.detail }
}

function DeviationRow({ row }) {
  return (
    <tr>
      <td className="mono">{row.value}</td>
      <td className="mono">{(row.first_seen || '').replace('T', ' ')}</td>
      <td className="mono">{(row.last_seen || '').replace('T', ' ')}</td>
    </tr>
  )
}

export default function DeviationsZ02() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [starting, setStarting] = useState(false)
  const jobId = data?.job?.status === 'running' ? data.job.id : null

  const refresh = useCallback(async () => {
    try {
      const d = await api.deviations()
      setData(d)
      setError(null)
      // while a job is in flight, also pull its live row count
      if (d.job?.status === 'running') {
        const j = await api.job(d.job.id)
        setData({ ...d, job: j })
      }
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = setInterval(refresh, jobId ? 3000 : 12000)
    return () => clearInterval(id)
  }, [jobId, refresh])

  const run = async () => {
    setStarting(true)
    try {
      await api.runDeviations()
      await refresh()
    } catch (e) {
      setError(e.message)
    } finally {
      setStarting(false)
    }
  }

  const running = data?.job?.status === 'running'
  const jobStatus = statusForJob(data?.job)
  const mismatch = data?.job?.status === 'success'
    && data.job.header_total != null
    && data.job.extracted !== data.job.header_total

  return (
    <StackLayout gap={5}>
      <Card accent="left" elevation="raised">
        <CardHeader>
          <FlexLayout justify="space-between" align="center">
            <Text styleAs="h4"> Loan Deviations Z2 — extraction</Text>
            <FlexLayout gap={2} align="center">
              {data?.view?.id && (
                <Link href={`/api/views/${data.view.id}/results.csv`}>
                  <DownloadIcon aria-hidden /> CSV
                </Link>
              )}
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
            <FlexLayout gap={6} align="center">
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

            {mismatch && (
              <FlexLayout gap={1} align="center">
                <StatusIndicator status="warning" />
                <Text>
                  count mismatch: header shows {data.job.header_total},
                  extracted {data.job.extracted} — investigate before trusting
                </Text>
              </FlexLayout>
            )}
            {data?.job?.status === 'success' && !mismatch && (
              <Text color="secondary" styleAs="label">
                cross-check ok: header {data.job.header_total} = extracted {data.job.extracted}
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
          <FlexLayout justify="space-between" align="center">
            <Text styleAs="h4">Deviations</Text>
            <Text color="secondary" styleAs="label">
              {data ? `${data.count} rows · first seen / last seen UTC` : 'loading…'}
            </Text>
          </FlexLayout>
        </CardHeader>
        <CardContent>
          {error && (
            <FlexLayout gap={1} align="center">
              <StatusIndicator status="error" />
              <Text status="error">{error}</Text>
            </FlexLayout>
          )}
          {!error && data && data.rows.length === 0 && (
            <FlexLayout gap={1} align="center">
              <StatusIndicator status="info" />
              <Text color="secondary">
                Nothing yet — run an extraction to pull the current list view.
              </Text>
            </FlexLayout>
          )}
          {!error && data && data.rows.length > 0 && (
            <div style={{ maxHeight: 480, overflowY: 'auto' }}>
              <table className="dev-table">
                <thead>
                  <tr>
                    <th>Deviation</th>
                    <th>First seen</th>
                    <th>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => <DeviationRow key={r.value} row={r} />)}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </StackLayout>
  )
}
