/**
 * The Deviations Z02 tab: the review deck and the accepted-deviations history.
 * The list/search view was removed — the deck is the working surface, history is the
 * record of what the deck approved.
 */

import type { JSX } from 'react'
import {
  Banner,
  BannerContent,
  FlexLayout,
  H1,
  Spinner,
  Text,
  ToggleButton,
  ToggleButtonGroup,
} from '@salt-ds/core'
import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { api } from '../api'
import type { DecisionKind, ItemRow } from '../api'
import { DecisionDeck } from '../components/DecisionDeck'
import { HistoryTable } from '../components/HistoryTable'
import { ItemDrawer } from '../components/ItemDrawer'
import { DECIDABLE_STATUSES, isDeckRow } from '../deck'
import { acceptAndSubmit } from '../submit'
import {
  useDecideDecision,
  useItem,
  useItems,
  usePatchFields,
  useSubmitJob,
  useSync,
  useUndoDecision,
  useWorkflows,
} from '../queries'

const Z02_WORKFLOW = 'deviations_z02'

export function DeviationsPage(): JSX.Element {
  const { key } = useParams()
  const navigate = useNavigate()
  const client = useQueryClient()
  const workflows = useWorkflows()
  // The Z02 tab is concrete; the registry only supplies labels and fields.
  const workflow = workflows.data?.find((item) => item.name === Z02_WORKFLOW) ?? workflows.data?.[0]
  const route = workflow?.route ?? null

  const [view, setView] = useState<'deck' | 'history'>('deck')
  const [historyQuery, setHistoryQuery] = useState('')
  const [historyPage, setHistoryPage] = useState(1)
  const [historySize, setHistorySize] = useState(25)
  const [announcement, setAnnouncement] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const [replaying, setReplaying] = useState(false)

  const sync = useSync(workflow?.name ?? null)
  // One unfiltered page powers the deck and the tallies, like the legacy deck.
  const deck = useItems(route, {}, 500, view === 'deck')
  // History is the accepted set, newest decision first, paginated by the server.
  const history = useItems(
    route,
    { decision: 'accept', q: historyQuery || undefined, sort: 'decision', order: 'desc' },
    historySize,
    view === 'history',
    (historyPage - 1) * historySize,
  )
  const detail = useItem(route, key ?? null)

  const allRows = useMemo(() => deck.data?.rows ?? [], [deck.data])
  const deckRows = useMemo(() => allRows.filter(isDeckRow), [allRows])
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
  const submit = useSubmitJob(route)

  /**
   * Accept is the deck's submission action (Option C): it stores the card's cleaned
   * values, records the decision, and enqueues the submit job when there is at least one
   * non-empty value. A card with no changes records the decision only. If the job cannot
   * be queued, the local accept is undone so the card stays actionable.
   *
   * Skip remains local: it records the decision and writes nothing to Salesforce.
   */
  async function handleDecide(
    row: ItemRow,
    decision: DecisionKind,
    values: Record<string, string | null>,
  ): Promise<boolean> {
    setActionError(null)
    try {
      const submitted = await acceptAndSubmit(decision, values, {
        patch: (changes) => patch.mutateAsync({ key: row.key, changes }),
        decide: (kind) => decide.mutateAsync({ key: row.key, decision: kind }),
        submit: () => submit.mutateAsync({ key: row.key }),
        undo: () => undo.mutateAsync({ key: row.key }),
      })
      const left = Math.max(0, deckRows.length - 1)
      const action =
        decision === 'accept'
          ? submitted
            ? 'Accepted & queued for update'
            : 'Accepted'
          : 'Skipped'
      setAnnouncement(
        `${action} ${row.key}` +
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
      (row) =>
        row.decision?.decision === 'reject' &&
        DECIDABLE_STATUSES.has(row.status),
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
          <ToggleButtonGroup
            aria-label="View"
            value={view}
            onChange={(event) => {
              const next = event.currentTarget.value
              if (next === 'deck' || next === 'history') setView(next)
            }}
          >
            <ToggleButton value="deck">Deck</ToggleButton>
            <ToggleButton value="history">History</ToggleButton>
          </ToggleButtonGroup>
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
          onHistory={() => setView('history')}
          onRefresh={() => void deck.refetch()}
          refreshing={deck.isFetching}
        />
      ) : (
        <HistoryTable
          rows={history.data?.rows ?? []}
          fields={workflow.fields}
          terminalLabels={workflow.terminalLabels}
          listUrl={workflow.listUrl}
          query={historyQuery}
          onQuery={(next) => {
            setHistoryQuery(next)
            setHistoryPage(1)
          }}
          page={historyPage}
          size={historySize}
          total={history.data?.total ?? 0}
          onPage={setHistoryPage}
          onSize={(next) => {
            setHistorySize(next)
            setHistoryPage(1)
          }}
          loading={history.isLoading}
          onOpen={(itemKey) => navigate(`/deviations-z02/${encodeURIComponent(itemKey)}`)}
        />
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
          <Banner status="error">
            <BannerContent>{detail.error.message}</BannerContent>
          </Banner>
        ) : (
          <Spinner />
        )
      ) : null}
    </FlexLayout>
  )
}
