/**
 * The Deviations Z02 tab. Opens on the review deck; the list view keeps the table,
 * filters and detail panel. Owns every query and mutation for this screen.
 */

import type { JSX } from 'react'
import { Button, FlexLayout, H1, Input, Spinner, Text } from '@salt-ds/core'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import type { DecisionKind } from '../api'
import { DecisionDeck } from '../components/DecisionDeck'
import { ItemDrawer } from '../components/ItemDrawer'
import { ItemsGrid } from '../components/ItemsGrid'
import {
  useDecideDecision,
  useItem,
  useItems,
  useSync,
  useUndoDecision,
  useWorkflows,
} from '../queries'

const Z02_WORKFLOW = 'deviations_z02'
/** Statuses the operator may decide on (FR-10.5). */
const DECIDABLE = ['ready', 'editing', 'needs_review']
const STATUSES = [
  'present',
  'ready',
  'editing',
  'submitting',
  'needs_review',
  'completed',
  'closed',
  'skipped',
]

export function DeviationsPage(): JSX.Element {
  const { key } = useParams()
  const navigate = useNavigate()
  const workflows = useWorkflows()
  // The Z02 tab is concrete; the registry only supplies labels and fields.
  const workflow = workflows.data?.find((item) => item.name === Z02_WORKFLOW) ?? workflows.data?.[0]
  const route = workflow?.route ?? null

  const [view, setView] = useState<'deck' | 'list'>('deck')
  const [status, setStatus] = useState('')
  const [decisionFilter, setDecisionFilter] = useState('')
  const [query, setQuery] = useState('')
  const [lastDecision, setLastDecision] = useState<{ key: string } | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

  const sync = useSync(workflow?.name ?? null)
  const deck = useItems(route, { statuses: DECIDABLE, decision: 'undecided' }, 200, view === 'deck')
  const list = useItems(
    route,
    {
      statuses: status ? [status] : undefined,
      decision: decisionFilter || undefined,
      q: query || undefined,
    },
    200,
    view === 'list',
  )
  const detail = useItem(route, key ?? null)

  const decide = useDecideDecision(route)
  const undo = useUndoDecision(route)
  const busyKey = decide.isPending ? (decide.variables?.key ?? null) : null

  function handleDecide(itemKey: string, decision: DecisionKind, reason?: string): void {
    setActionError(null)
    const before = deck.data?.rows.length ?? 1
    decide.mutate(
      { key: itemKey, decision, reason },
      {
        onSuccess: () => {
          setLastDecision({ key: itemKey })
          setAnnouncement(
            `${decision === 'accept' ? 'Accepted' : 'Rejected'} ${itemKey}` +
              (before > 1 ? ` · ${before - 1} to review` : ' · nothing left to review'),
          )
        },
        onError: (error) => setActionError(error.message),
      },
    )
  }

  function handleUndo(itemKey: string): void {
    setActionError(null)
    undo.mutate(
      { key: itemKey },
      {
        onSuccess: () => {
          if (lastDecision?.key === itemKey) setLastDecision(null)
          setAnnouncement(`Restored ${itemKey} to the deck`)
        },
        onError: (error) => setActionError(error.message),
      },
    )
  }

  function showList(decision: string): void {
    setDecisionFilter(decision)
    setView('list')
  }

  if (workflows.isLoading) return <Spinner />
  if (!workflow) return <Text>The Deviations Z02 workflow is not registered.</Text>

  return (
    <FlexLayout direction="column" gap={4}>
      <FlexLayout justify="space-between" align="center">
        <H1>{workflow.label}</H1>
        <Text color="secondary">
          {sync.data ? `${sync.data.rowsRead} rows in the last refresh` : 'no refresh yet'}
        </Text>
      </FlexLayout>

      <div className="view-toggle" role="group" aria-label="View">
        <Button
          appearance={view === 'deck' ? 'solid' : 'bordered'}
          aria-pressed={view === 'deck'}
          onClick={() => setView('deck')}
        >
          Deck
        </Button>
        <Button
          appearance={view === 'list' ? 'solid' : 'bordered'}
          aria-pressed={view === 'list'}
          onClick={() => setView('list')}
        >
          List
        </Button>
      </div>

      {view === 'deck' ? (
        <DecisionDeck
          rows={deck.data?.rows ?? []}
          fields={workflow.fields}
          terminalLabels={workflow.terminalLabels}
          busyKey={busyKey}
          undoBusy={undo.isPending}
          canUndo={lastDecision !== null}
          error={actionError ?? (deck.error ? deck.error.message : null)}
          announcement={announcement}
          enabled={key === undefined}
          onDecide={handleDecide}
          onUndo={() => {
            if (lastDecision) handleUndo(lastDecision.key)
          }}
          onOpen={(itemKey) => navigate(`/deviations-z02/${encodeURIComponent(itemKey)}`)}
          onShowList={showList}
          onReload={() => void deck.refetch()}
          reloading={deck.isFetching}
        />
      ) : (
        <>
          <FlexLayout gap={2} align="end" className="filters">
            <label>
              <Text>Status</Text>
              <select
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                aria-label="Filter by status"
              >
                <option value="">All</option>
                {STATUSES.map((option) => (
                  <option key={option} value={option}>
                    {option.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <Text>Decision</Text>
              <select
                value={decisionFilter}
                onChange={(event) => setDecisionFilter(event.target.value)}
                aria-label="Filter by decision"
              >
                <option value="">Any</option>
                <option value="undecided">Undecided</option>
                <option value="accept">Accepted</option>
                <option value="reject">Rejected</option>
              </select>
            </label>
            <label>
              <Text>Search</Text>
              <Input
                value={query}
                inputProps={{
                  onChange: (event) => setQuery(event.target.value),
                  placeholder: 'Deviation number',
                }}
              />
            </label>
            <Button
              appearance="bordered"
              onClick={() => void list.refetch()}
              disabled={list.isFetching}
            >
              Reload
            </Button>
          </FlexLayout>

          {list.isLoading ? <Spinner /> : null}
          {list.error ? <Text className="reason">{list.error.message}</Text> : null}
          {list.data && list.data.rows.length === 0 ? (
            <Text color="secondary">No items match. Clear the filters or refresh the list.</Text>
          ) : null}
          {list.data && list.data.rows.length > 0 ? (
            <ItemsGrid
              rows={list.data.rows}
              fields={workflow.fields}
              terminalLabels={workflow.terminalLabels}
              onOpen={(itemKey) => navigate(`/deviations-z02/${encodeURIComponent(itemKey)}`)}
            />
          ) : null}
        </>
      )}

      {key ? (
        detail.data ? (
          <ItemDrawer
            detail={detail.data}
            fields={workflow.fields}
            refKinds={workflow.refKinds}
            terminalLabels={workflow.terminalLabels}
            onClose={() => navigate('/deviations-z02')}
            onUndoDecision={() => handleUndo(detail.data.key)}
            undoing={undo.isPending}
          />
        ) : detail.error ? (
          <Text className="reason">{detail.error.message}</Text>
        ) : (
          <Spinner />
        )
      ) : null}
    </FlexLayout>
  )
}
