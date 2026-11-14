/**
 * LMS2 Contract Approval: paste links, then watch the durable approval audit.
 *
 * Queueing a link is the only operator action. The table is the history snapshot store,
 * which is updated after every job and survives the current-data purge; there is no
 * separate live queue table to duplicate it.
 */

import type { JSX } from 'react'
import {
  Banner,
  BannerContent,
  Button,
  FlexLayout,
  H1,
  H2,
  MultilineInput,
  Spinner,
  StackLayout,
  Text,
} from '@salt-ds/core'
import { useState } from 'react'

import { ApprovalHistoryTable } from '../components/ApprovalHistoryTable'
import type { HistoryFilters } from '../queries'
import {
  EMPTY_HISTORY_FILTERS,
  useHistory,
  useQueueLinks,
  useWorkflows,
} from '../queries'

const APPROVAL_WORKFLOW = 'lms2_approval'

export function Lms2ApprovalsPage(): JSX.Element {
  const workflows = useWorkflows()
  const workflow =
    workflows.data?.find((item) => item.name === APPROVAL_WORKFLOW) ?? null
  const route = workflow?.route ?? null

  const [links, setLinks] = useState('')
  const [notice, setNotice] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const [historyFilters, setHistoryFilters] =
    useState<HistoryFilters>(EMPTY_HISTORY_FILTERS)
  const [historyPage, setHistoryPage] = useState(1)
  const [historySize, setHistorySize] = useState(25)

  const history = useHistory(
    route,
    historyFilters,
    historySize,
    true,
    (historyPage - 1) * historySize,
  )
  const queueLinks = useQueueLinks(route)

  async function queuePastedLinks(): Promise<void> {
    const lines = links
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line !== '')
    if (lines.length === 0) return
    setNotice('')
    setActionError(null)
    try {
      const result = await queueLinks.mutateAsync(lines)
      setLinks('')
      setNotice(
        `${result.queued} queued${result.skipped > 0 ? `, ${result.skipped} skipped` : ''}`,
      )
      if (result.rejected.length > 0) {
        setActionError(
          result.rejected
            .map((rejected) => `${rejected.link}: ${rejected.reason}`)
            .join(' · '),
        )
      }
    } catch (error) {
      setActionError(
        error instanceof Error ? error.message : 'could not queue the links',
      )
    }
  }

  if (workflows.isLoading) return <Spinner />
  if (!workflow) return <Text>The LMS2 Contract Approval workflow is not registered.</Text>

  const hasLinks = links.trim() !== ''

  return (
    <FlexLayout direction="column" gap={2}>
      <H1>{workflow.label}</H1>
      <StackLayout gap={1}>
        <Text color="secondary">
          Paste one LMS2 CL contract link or loan ID per line. Each accepted line is
          approved automatically; no further action is needed.
        </Text>
        <MultilineInput
          value={links}
          rows={5}
          bordered
          placeholder="https://hffc.lightning.force.com/lightning/n/CL_Contract_Detail?c__loanId=…"
          textAreaProps={{
            'aria-label': 'LMS2 CL contract links',
            onChange: (event) => setLinks(event.target.value),
          }}
        />
        <FlexLayout gap={1} align="center" wrap>
          <Button
            appearance="solid"
            disabled={!hasLinks || queueLinks.isPending}
            onClick={() => void queuePastedLinks()}
          >
            {queueLinks.isPending ? 'Queueing…' : 'Queue approvals'}
          </Button>
          {notice ? <Text color="secondary">{notice}</Text> : null}
        </FlexLayout>
        {actionError ? (
          <Banner status="error">
            <BannerContent>{actionError}</BannerContent>
          </Banner>
        ) : null}
        <FlexLayout justify="space-between" align="baseline" gap={2} wrap>
          <H2>Approval history</H2>
          <Text color="secondary">
            {history.data?.total ?? 0} contract
            {(history.data?.total ?? 0) === 1 ? '' : 's'} · durable audit
          </Text>
        </FlexLayout>
        <ApprovalHistoryTable
          rows={history.data?.rows ?? []}
          total={history.data?.total ?? 0}
          filters={historyFilters}
          onFilters={(next) => {
            setHistoryFilters(next)
            setHistoryPage(1)
          }}
          page={historyPage}
          size={historySize}
          onPage={setHistoryPage}
          onSize={(next) => {
            setHistorySize(next)
            setHistoryPage(1)
          }}
          loading={history.isLoading}
          terminalLabels={workflow.terminalLabels}
        />
      </StackLayout>
    </FlexLayout>
  )
}
