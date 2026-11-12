/**
 * The review deck, kept in the legacy deck's shape: one card, tallies, the same four
 * editable parameters and full-width Skip/Accept buttons. Accept now also queues the
 * update when the card has changed values; Skip remains local. Cards leave with the
 * legacy slide animation after the server confirms.
 *
 * Two deliberate keyboard shortcuts mirror the buttons: Shift+← skips and Shift+→ accepts
 * (FR-10.9). They are ignored while a text field has focus, while a dialog is open, with
 * another modifier held, and on key auto-repeat, so typing or a stray key can never
 * accept a deviation.
 */

import type { JSX } from 'react'
import {
  Button,
  Card,
  CardContent,
  FlexLayout,
  GridLayout,
  Spinner,
  StackLayout,
  StatusIndicator,
  Text,
} from '@salt-ds/core'
import { DoubleChevronLeftIcon, RefreshIcon, SuccessIcon } from '@salt-ds/icons'
import { useEffect, useRef, useState } from 'react'

import type { DecisionKind, ItemDetail, ItemRow, WorkflowFieldView } from '../api'
import { changesFor, draftFor } from '../format'
import { DecisionCard } from './DecisionCard'
import { DeckPicker } from './DeckPicker'

export interface DeckTally {
  accept: number
  skip: number
  pending: number
}

interface Props {
  /** The card order: pinned rows first, then the natural deck order. */
  rows: ItemRow[]
  /** Natural deck order for the picker's options, so its list stays stable. */
  pickerRows: ItemRow[]
  /** Keys pinned by the operator, in check order. */
  selection: string[]
  /** Report a new checked-key list to the page that owns the pins. */
  onSelection: (keys: string[]) => void
  fields: WorkflowFieldView[]
  terminalLabels: Record<string, string>
  detail: ItemDetail | null
  tally: DeckTally
  error: string | null
  announcement: string
  listUrl: string
  onDecide: (
    row: ItemRow,
    decision: DecisionKind,
    values: Record<string, string | null>,
  ) => Promise<boolean>
  onReplay: () => void
  replaying: boolean
  /** Queue one more extraction for the top card's item. */
  onRetryExtraction: (key: string) => void
  /** A retry request is in flight. */
  retrying: boolean
  onHistory: () => void
  onRefresh: () => void
  refreshing: boolean
}

export function DecisionDeck({
  rows,
  pickerRows,
  selection,
  onSelection,
  fields,
  terminalLabels,
  detail,
  tally,
  error,
  announcement,
  listUrl,
  onDecide,
  onReplay,
  replaying,
  onHistory,
  onRefresh,
  refreshing,
  onRetryExtraction,
  retrying,
}: Props): JSX.Element {
  const [pending, setPending] = useState<DecisionKind | null>(null)
  const [leaving, setLeaving] = useState<{ row: ItemRow; decision: DecisionKind } | null>(null)
  const [draft, setDraft] = useState<{ key: string; values: Record<string, string> } | null>(null)

  // Sticky focus: the card on screen only changes when the operator decides it or pins
  // another one. Without this, any membership change (a failed submission coming back, a
  // new deviation, the startup audit) would rebind the position-based `rows[0]` and swap
  // the card under the operator's hands.
  const [focus, setFocus] = useState<string | null>(null)
  const pinnedKey = selection[0] ?? null
  const remembered = focus !== null && rows.some((row) => row.key === focus) ? focus : null
  const topKey = leaving?.row.key ?? pinnedKey ?? remembered ?? rows[0]?.key ?? null
  const top = leaving?.row ?? rows.find((row) => row.key === topKey) ?? rows[0]
  // Adopt the card that ended up on top, so the next render remembers it. Adjusting state
  // during render (rather than in an effect) is the documented React pattern for deriving
  // state from props; the guard makes it settle after one extra render.
  if (topKey !== focus) {
    setFocus(topKey)
  }
  const initial = top === undefined
    ? {}
    : Object.fromEntries(fields.map((field) => [field.key, draftFor(field, top)]))
  const values = top !== undefined && draft?.key === top.key ? draft.values : initial
  // The card that will be shown once the current one is decided. With sticky focus the
  // current card is not necessarily rows[0], so this is the first row that is not it.
  const upcoming = rows.find((row) => row.key !== top?.key)
  const busy = pending !== null || leaving !== null
  const canAct = top !== undefined && !busy

  async function decide(decision: DecisionKind): Promise<void> {
    if (top === undefined || !canAct) return
    setPending(decision)
    const changes = decision === 'accept' ? changesFor(fields, values) : {}
    const ok = await onDecide(top, decision, changes)
    setPending(null)
    if (!ok) return
    setLeaving({ row: top, decision })
    window.setTimeout(() => setLeaving(null), 420)
  }

  /**
   * Bind the deck's keyboard shortcuts for as long as this deck is mounted. The card
   * itself is not focusable, so the listener sits on the window; it calls the same
   * `decide` path as the buttons (server confirmation, then the exit animation).
   * Ignored while a text field or open dialog owns the keystroke, when a second modifier
   * is held, on auto-repeat, and whenever the deck cannot act (in flight or complete),
   * so a held or stray key cannot accept a deviation. The handler reads the latest state
   * through a ref, so the listener is bound once instead of on every render.
   */
  const latest = useRef({ canAct, decide })
  useEffect(() => {
    latest.current = { canAct, decide }
  })
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
      if (!event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return
      if (event.repeat || !latest.current.canAct) return
      const target = event.target
      if (
        target instanceof HTMLElement &&
        target.closest(
          'input, textarea, select, [contenteditable="true"], [role="dialog"], [role="tablist"]',
        ) !== null
      ) {
        return
      }
      event.preventDefault()
      void latest.current.decide(event.key === 'ArrowRight' ? 'accept' : 'reject')
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const leavingClass =
    leaving === null ? null : leaving.decision === 'accept' ? 'deck-out-right' : 'deck-out-left'

  return (
    <StackLayout gap={1}>
      <FlexLayout justify="space-between" align="center" gap={2} wrap className="deck-bar">
        <FlexLayout gap={2} align="center" wrap>
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
        <Button appearance="bordered" onClick={onRefresh} disabled={refreshing}>
          <RefreshIcon aria-hidden /> Reload deck
        </Button>
      </FlexLayout>

      <Text aria-live="polite" color="secondary" styleAs="label" className="deck-bar">
        {announcement}
      </Text>

      {error ? (
        <FlexLayout gap={1} align="center">
          <StatusIndicator status="error" />
          <Text color="error">{error}</Text>
        </FlexLayout>
      ) : null}

      {pickerRows.length > 0 ? (
        <DeckPicker
          rows={pickerRows}
          selected={selection}
          onSelected={onSelection}
        />
      ) : null}

      {top === undefined ? (
        <Card elevation="raised" accent="top">
          <CardContent>
            <StackLayout gap={1} className="deck-complete">
              <Text styleAs="h3">Deck complete 🎉</Text>
              <Text color="secondary">
                {tally.accept} accepted · {tally.skip} skipped. Accepted items with changed
                values are queued for update and verified in the background; Implement
                remains disabled until the final phase.
              </Text>
              <FlexLayout gap={2} justify="center" className="deck-complete-actions">
                {tally.skip > 0 ? (
                  <Button appearance="bordered" onClick={onReplay} disabled={replaying}>
                    {replaying ? <Spinner size="small" /> : null}
                    Replay skipped ({tally.skip})
                  </Button>
                ) : null}
                <Button appearance="bordered" onClick={onHistory}>
                  View history
                </Button>
                <Button appearance="bordered" onClick={onRefresh} disabled={refreshing}>
                  <RefreshIcon aria-hidden /> Reload deck
                </Button>
              </FlexLayout>
            </StackLayout>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className={`deck-card-wrap deck-card ${leavingClass ?? ''}`}>
            <DecisionCard
              row={top}
              fields={fields}
              terminalLabels={terminalLabels}
              detail={detail}
              values={values}
              listUrl={listUrl}
              onField={(key, value) => {
                setDraft({ key: top.key, values: { ...values, [key]: value } })
              }}
              onRetryExtraction={() => onRetryExtraction(top.key)}
              retrying={retrying}
            />
          </div>

          <GridLayout columns={2} gap={1} className="deck-bar">
            <Button
              appearance="solid"
              disabled={!canAct}
              onClick={() => void decide('reject')}
              aria-keyshortcuts="Shift+ArrowLeft"
              style={{ width: '100%', minHeight: 40 }}
            >
              <DoubleChevronLeftIcon aria-hidden /> Skip (Shift+←)
            </Button>
            <Button
              sentiment="accented"
              appearance="solid"
              disabled={!canAct}
              onClick={() => void decide('accept')}
              aria-keyshortcuts="Shift+ArrowRight"
              style={{ width: '100%', minHeight: 40 }}
            >
              <SuccessIcon aria-hidden /> Accept &amp; update (Shift+→)
            </Button>
          </GridLayout>

          {upcoming ? (
            <Text color="secondary" styleAs="label">
              next up: {upcoming.key}
            </Text>
          ) : null}
        </>
      )}
    </StackLayout>
  )
}
