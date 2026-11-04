/**
 * The review deck, kept in the legacy deck's shape: one card, tallies, the same four
 * editable parameters and Skip/Accept buttons. Cards leave with the legacy slide
 * animation after the server confirms; swipe and arrow keys are accelerators for the
 * same two actions.
 */

import type { JSX, PointerEvent as ReactPointerEvent } from 'react'
import {
  Button,
  Card,
  CardContent,
  FlexLayout,
  Spinner,
  StackLayout,
  StatusIndicator,
  Text,
} from '@salt-ds/core'
import { DoubleChevronRightIcon, SuccessIcon } from '@salt-ds/icons'
import { useEffect, useRef, useState } from 'react'

import type { DecisionKind, ItemDetail, ItemRow, WorkflowFieldView } from '../api'
import { changesFor, draftFor } from '../format'
import { DecisionCard } from './DecisionCard'

export interface DeckTally {
  accept: number
  skip: number
  pending: number
}

interface Props {
  rows: ItemRow[]
  fields: WorkflowFieldView[]
  terminalLabels: Record<string, string>
  detail: ItemDetail | null
  tally: DeckTally
  error: string | null
  announcement: string
  /** False while the detail panel is open, so keys do not act behind it. */
  enabled: boolean
  onDecide: (
    row: ItemRow,
    decision: DecisionKind,
    values: Record<string, string | null>,
  ) => Promise<boolean>
  onReplay: () => void
  replaying: boolean
  onOpen: (key: string) => void
  onRefresh: () => void
  refreshing: boolean
}

interface DragState {
  startX: number
  dx: number
  width: number
}

function threshold(width: number): number {
  return Math.max(88, Math.min(140, width * 0.3))
}

export function DecisionDeck({
  rows,
  fields,
  terminalLabels,
  detail,
  tally,
  error,
  announcement,
  enabled,
  onDecide,
  onReplay,
  replaying,
  onOpen,
  onRefresh,
  refreshing,
}: Props): JSX.Element {
  const [drag, setDrag] = useState<DragState | null>(null)
  const [pending, setPending] = useState<DecisionKind | null>(null)
  const [leaving, setLeaving] = useState<{ row: ItemRow; decision: DecisionKind } | null>(null)
  const [draft, setDraft] = useState<{ key: string; values: Record<string, string> } | null>(null)

  const top = leaving?.row ?? rows[0]
  const initial = top === undefined
    ? {}
    : Object.fromEntries(fields.map((field) => [field.key, draftFor(field, top)]))
  const values = top !== undefined && draft?.key === top.key ? draft.values : initial
  const busy = pending !== null || leaving !== null
  const canAct = enabled && top !== undefined && !busy

  const decideRef = useRef<(decision: DecisionKind) => Promise<void>>(async () => {})

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
  useEffect(() => {
    decideRef.current = decide
  })

  useEffect(() => {
    if (!enabled) return
    const onKey = (event: KeyboardEvent): void => {
      const target = event.target
      if (
        target instanceof HTMLElement &&
        ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'A'].includes(target.tagName)
      ) {
        return
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (event.key === 'ArrowRight') {
        event.preventDefault()
        void decideRef.current('accept')
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault()
        void decideRef.current('reject')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled])

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>): void {
    if (!canAct || event.button !== 0) return
    const target = event.target
    if (
      target instanceof HTMLElement &&
      target.closest('button, a, input, [data-no-swipe]')
    ) {
      return
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    setDrag({
      startX: event.clientX,
      dx: 0,
      width: event.currentTarget.clientWidth,
    })
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>): void {
    if (drag === null) return
    setDrag({ ...drag, dx: event.clientX - drag.startX })
  }

  function handlePointerUp(): void {
    if (drag === null) return
    const limit = threshold(drag.width)
    if (Math.abs(drag.dx) >= limit) {
      void decide(drag.dx > 0 ? 'accept' : 'reject')
    }
    setDrag(null)
  }

  const limit = drag === null ? 1 : threshold(drag.width)
  const ratio = drag === null ? 0 : Math.min(1, Math.abs(drag.dx) / limit)
  const direction: DecisionKind | null =
    drag === null || Math.abs(drag.dx) < 8 ? null : drag.dx > 0 ? 'accept' : 'reject'
  const leavingClass =
    leaving === null ? null : leaving.decision === 'accept' ? 'deck-out-right' : 'deck-out-left'
  const dragStyle =
    drag === null
      ? undefined
      : { transform: `translateX(${drag.dx}px) rotate(${drag.dx / 24}deg)` }

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
          Refresh
        </Button>
      </FlexLayout>

      <p className="deck-announcement" aria-live="polite">
        {announcement}
      </p>

      {error ? (
        <FlexLayout gap={1} align="center">
          <StatusIndicator status="error" />
          <Text color="error">{error}</Text>
        </FlexLayout>
      ) : null}

      {top === undefined ? (
        <Card elevation="raised" accent="top">
          <CardContent>
            <StackLayout gap={1} className="deck-complete">
              <Text styleAs="h3">Deck complete 🎉</Text>
              <Text color="secondary">
                {tally.accept} accepted · {tally.skip} skipped. Accepted parameters are
                stored as proposals; accepted items wait for the submitter and nothing has
                been written to Salesforce yet.
              </Text>
              <FlexLayout gap={2} justify="center" className="deck-complete-actions">
                {tally.skip > 0 ? (
                  <Button appearance="bordered" onClick={onReplay} disabled={replaying}>
                    {replaying ? <Spinner size="small" /> : null}
                    Replay skipped ({tally.skip})
                  </Button>
                ) : null}
                <Button appearance="bordered" onClick={onRefresh} disabled={refreshing}>
                  Refresh
                </Button>
              </FlexLayout>
            </StackLayout>
          </CardContent>
        </Card>
      ) : (
        <>
          <div
            className={`deck-card-wrap deck-card ${leavingClass ?? ''}`}
            data-dragging={drag !== null ? 'true' : undefined}
            style={dragStyle}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={() => setDrag(null)}
          >
            <DecisionCard
              row={top}
              fields={fields}
              terminalLabels={terminalLabels}
              detail={detail}
              values={values}
              offset={0}
              leavingClass={null}
              onField={(key, value) => {
                setDraft({ key: top.key, values: { ...values, [key]: value } })
              }}
              onDetails={() => onOpen(top.key)}
            />
            {direction !== null ? (
              <div
                className="swipe-stamp"
                data-kind={direction}
                style={{ opacity: ratio }}
                aria-hidden
              >
                {direction === 'accept' ? 'ACCEPT' : 'SKIP'}
              </div>
            ) : null}
          </div>

          <FlexLayout justify="center" gap={3} align="center">
            <Button
              appearance="solid"
              disabled={!canAct}
              onClick={() => void decide('reject')}
              className="deck-skip"
            >
              <DoubleChevronRightIcon aria-hidden /> Skip
            </Button>
            <Button
              sentiment="accented"
              appearance="solid"
              disabled={!canAct}
              onClick={() => void decide('accept')}
            >
              <SuccessIcon aria-hidden /> Accept
            </Button>
          </FlexLayout>

          {rows[1] ? (
            <Text color="secondary" styleAs="label" className="deck-next">
              next up: {rows[1].key}
            </Text>
          ) : null}
        </>
      )}
    </StackLayout>
  )
}
