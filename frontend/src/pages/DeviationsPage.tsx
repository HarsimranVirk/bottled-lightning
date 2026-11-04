/**
 * The Deviations Z02 tab. Opens on the review deck; the list view keeps the table,
 * filters and detail panel. Owns every query and mutation for this screen.
 */

import type { JSX } from 'react'
import { Button, FlexLayout, H1, Input, Spinner, Text } from '@salt-ds/core'
import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { api } from '../api'
import type { DecisionKind, ItemRow } from '../api'
import { DecisionDeck } from '../components/DecisionDeck'
import { ItemDrawer } from '../components/ItemDrawer'
import { ItemsGrid } from '../components/ItemsGrid'
import {
  useDecideDecision,
  useItem,
  useItems,
  usePatchFields,
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
  const client = useQueryClient()
  const workflows = useWorkflows()
  // The Z02 tab is concrete; the registry only supplies labels and fields.
  const workflow = workflows.data?.find((item) => item.name === Z02_WORKFLOW) ?? workflows.data?.[0]
  const route = workflow?.route ?? null

  const [view, setView] = useState<'deck' | 'list'>('deck')
  const [status, setStatus] = useState('')
  const [decisionFilter, setDecisionFilter] = useState('')
  const [query, setQuery] = useState('')
  const [announcement, setAnnouncement] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const [replaying, setReplaying] = useState(false)

  const sync = useSync(workflow?.name ?? null)
  // One unfiltered page powers the deck and the tallies, like the legacy deck.
  const deck = useItems(route, {}, 500, view === 'deck')
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

  const allRows = useMemo(() => deck.data?.rows ?? [], [deck.data])
  const deckRows = useMemo(
    () => allRows.filter((row) => DECIDABLE.includes(row.status) && row.decision === null),
    [allRows],
  )
  const tally = useMemo(
    () => ({
      accept: allRows.filter((row) => row.decision?.decision === 'accept').length,
      skip: allRows.filter((row) => row.decision?.decision === 'reject').length,
      pending: deckRows.length,
    }),
    [allRows, deckRows],
  )

  const topKey = deckRows[0]?.key ?? null
  const cardDetail = useItem(route, view === 'deck' ? topKey : null)

  const decide = useDecideDecision(route)
  const patch = usePatchFields(route)
  const undo = useUndoDecision(route)

  /**
   * Accept stores the card's edited values as proposals first, then records the
   * decision — the legacy deck's behaviour on the new API (FR-10.6). Skip records the
   * decision only. Returns false on failure so the deck keeps the card.
   */
  async function handleDecide(
    row: ItemRow,
    decision: DecisionKind,
    values: Record<string, string | null>,
  ): Promise<boolean> {
    setActionError(null)
    try {
      if (decision === 'accept') {
        await patch.mutateAsync({ key: row.key, changes: values })
      }
      await decide.mutateAsync({ key: row.key, decision })
      const left = Math.max(0, deckRows.length - 1)
      setAnnouncement(
        `${decision === 'accept' ? 'Accepted' : 'Skipped'} ${row.key}` +
          (left === 0 ? ' · deck complete' : ` · ${left} to review`),
      )
      return true
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'decision failed')
      return false
    }
  }

  function handleUndo(itemKey: string): void {
    setActionError(null)
    undo.mutate(
      { key: itemKey },
      {
        onSuccess: () => setAnnouncement(`Restored ${itemKey}`),
        onError: (error) => setActionError(error.message),
      },
    )
  }

  /** Undo every skipped decision and put those cards back in the deck. */
  async function replaySkipped(): Promise<void> {
    if (route === null) return
    const skipped = allRows.filter(
      (row) => row.decision?.decision === 'reject' && DECIDABLE.includes(row.status),
    )
    if (skipped.length === 0) return
    setReplaying(true)
    setActionError(null)
    try {
      await Promise.all(skipped.map((row) => api.undoDecision(route, row.key)))
      setAnnouncement(`Restored ${skipped.length} skipped to the deck`)
      await client.invalidateQueries({ queryKey: ['items', route] })
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'replay failed')
    } finally {
      setReplaying(false)
    }
  }

  if (workflows.isLoading) return <Spinner />
  if (!workflow) return <Text>The Deviations Z02 workflow is not registered.</Text>

  return (
    <FlexLayout direction="column" gap={2}>
      <FlexLayout justify="space-between" align="center" gap={2} wrap>
        <H1>{workflow.label}</H1>
        <FlexLayout gap={2} align="center" wrap>
          <Text color="secondary">
            {sync.data ? `${sync.data.rowsRead} rows in the last refresh` : 'no refresh yet'}
          </Text>
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
        </FlexLayout>
      </FlexLayout>

      {view === 'deck' ? (
        <DecisionDeck
          rows={deckRows}
          fields={workflow.fields}
          terminalLabels={workflow.terminalLabels}
          detail={cardDetail.data ?? null}
          tally={tally}
          error={actionError ?? (deck.error ? deck.error.message : null)}
          announcement={announcement}
          listUrl={workflow.listUrl}
          onDecide={handleDecide}
          onReplay={() => void replaySkipped()}
          replaying={replaying}
          onRefresh={() => void deck.refetch()}
          refreshing={deck.isFetching}
        />
      ) : (
        <>
          <FlexLayout gap={1} align="end" className="filters">
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
