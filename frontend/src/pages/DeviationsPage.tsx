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
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { api } from '../api'
import type { DecisionKind, ItemRow } from '../api'
import { DecisionDeck } from '../components/DecisionDeck'
import { HistoryTable } from '../components/HistoryTable'
import { ItemDrawer } from '../components/ItemDrawer'
import { DECIDABLE_STATUSES, isDeckRow, orderDeckRows } from '../deck'
import { acceptAndSubmit } from '../submit'
import type { HistoryFilters } from '../queries'
import {
  EMPTY_HISTORY_FILTERS,
  useDecideDecision,
  useHistory,
  useHistoryItem,
  useItem,
  useItems,
  usePatchFields,
  useRetryExtraction,
  useSubmitJob,
  useSync,
  useUndoDecision,
  useWorkflows,
} from '../queries'

const Z02_WORKFLOW = 'deviations_z02'

/**
 * One deck pin. The epoch is the row's presence epoch, so a pin is only live while the
 * same presence of that key is still in the deck; an item that leaves and returns gets a
 * new epoch and does not silently jump back to the top.
 */
interface DeckPin {
  key: string
  epoch: number
}

export function DeviationsPage(): JSX.Element {
  const { key } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const view = searchParams.get('view') === 'history' ? 'history' : 'deck'
  const client = useQueryClient()
  const workflows = useWorkflows()
  // The Z02 tab is concrete; the registry only supplies labels and fields.
  const workflow = workflows.data?.find((item) => item.name === Z02_WORKFLOW) ?? workflows.data?.[0]
  const route = workflow?.route ?? null

  const [historyFilters, setHistoryFilters] =
    useState<HistoryFilters>(EMPTY_HISTORY_FILTERS)
  const [historyPage, setHistoryPage] = useState(1)
  const [historySize, setHistorySize] = useState(25)
  const [announcement, setAnnouncement] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const [replaying, setReplaying] = useState(false)
  // Pins are ephemeral and local to this page; they only reorder the fetched rows.
  const [pins, setPins] = useState<DeckPin[]>([])

  const sync = useSync(workflow?.name ?? null)
  // One unfiltered page powers the deck and the tallies, like the legacy deck.
  const deck = useItems(route, {}, 500, view === 'deck')
  // History is the approved snapshot store, newest accept first, paginated by the server.
  const history = useHistory(
    route,
    historyFilters,
    historySize,
    view === 'history',
    (historyPage - 1) * historySize,
  )
  const currentDetail = useItem(route, view === 'deck' ? key ?? null : null)
  const historyDetail = useHistoryItem(route, view === 'history' ? key ?? null : null)
  const detail = view === 'history' ? historyDetail : currentDetail

  const allRows = useMemo(() => deck.data?.rows ?? [], [deck.data])
  const deckRows = useMemo(() => allRows.filter(isDeckRow), [allRows])
  const rowByKey = useMemo(
    () => new Map(deckRows.map((row) => [row.key, row])),
    [deckRows],
  )
  // A pin whose row left the deck (decided, absent or purged) has nothing to reorder.
  const pinnedKeys = useMemo(
    () =>
      pins.flatMap((pin) => {
        const row = rowByKey.get(pin.key)
        return row !== undefined && row.epoch === pin.epoch ? [pin.key] : []
      }),
    [pins, rowByKey],
  )
  const orderedRows = useMemo(
    () => orderDeckRows(deckRows, pinnedKeys),
    [deckRows, pinnedKeys],
  )
  const tally = useMemo(
    () => ({
      accept: allRows.filter((row) => row.decision?.decision === 'accept').length,
      skip: allRows.filter((row) => row.decision?.decision === 'reject').length,
      pending: deckRows.length,
    }),
    [allRows, deckRows],
  )

  const topKey = orderedRows[0]?.key ?? null
  const cardDetail = useItem(route, view === 'deck' ? topKey : null)

  function showView(next: 'deck' | 'history'): void {
    navigate(next === 'history' ? '/deviations-z02?view=history' : '/deviations-z02')
  }

  const decide = useDecideDecision(route)
  const patch = usePatchFields(route)
  const undo = useUndoDecision(route)
  const submit = useSubmitJob(route)
  const retryExtraction = useRetryExtraction(route)

  /**
   * Replace the pin list with the picker's checked keys, in check order. Each pin stores
   * the row's current epoch so a later poll that removes and re-adds the key cannot make
   * an old pin live again (D-08).
   */
  function handleSelection(keys: string[]): void {
    setPins(
      keys.flatMap((key) => {
        const row = rowByKey.get(key)
        return row === undefined ? [] : [{ key, epoch: row.epoch }]
      }),
    )
  }

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
      setPins((current) => current.filter((pin) => pin.key !== row.key))
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

  /** The card asks for another extraction; the backend owns whether it is allowed. */
  function handleRetryExtraction(itemKey: string): void {
    setActionError(null)
    retryExtraction.mutate(
      { key: itemKey },
      {
        onSuccess: () => setAnnouncement(`Retrying extraction for ${itemKey}`),
        onError: (error) => setActionError(error.message),
      },
    )
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
              if (next === 'deck' || next === 'history') showView(next)
            }}
          >
            <ToggleButton value="deck">Deck</ToggleButton>
            <ToggleButton value="history">History</ToggleButton>
          </ToggleButtonGroup>
        </FlexLayout>
      </FlexLayout>

      {view === 'deck' ? (
        <DecisionDeck
          rows={orderedRows}
          pickerRows={deckRows}
          selection={pinnedKeys}
          onSelection={handleSelection}
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
          onRetryExtraction={handleRetryExtraction}
          retrying={retryExtraction.isPending}
          onHistory={() => showView('history')}
          onRefresh={() => void deck.refetch()}
          refreshing={deck.isFetching}
        />
      ) : (
        <HistoryTable
          rows={history.data?.rows ?? []}
          fields={workflow.fields}
          terminalLabels={workflow.terminalLabels}
          listUrl={workflow.listUrl}
          filters={historyFilters}
          onFilters={(next) => {
            setHistoryFilters(next)
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
          onOpen={(itemKey) =>
            navigate(
              `/deviations-z02/${encodeURIComponent(itemKey)}?view=history`,
            )
          }
        />
      )}

      {key ? (
        detail.data ? (
          <ItemDrawer
            detail={detail.data}
            fields={workflow.fields}
            refKinds={workflow.refKinds}
            terminalLabels={workflow.terminalLabels}
            onClose={() => showView(view)}
            onUndoDecision={
              view === 'deck' ? () => handleUndo(detail.data.key) : undefined
            }
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
