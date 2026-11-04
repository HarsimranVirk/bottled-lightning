/**
 * Swipeable review deck: one card at a time, accept/reject with pointer, buttons or keys.
 *
 * Decisions are not optimistic: the card leaves only when the parent's mutation succeeds
 * and the deck query refetches. Dragging therefore never implies a decision — releasing
 * past the threshold calls the same callback as the buttons.
 */

import type { JSX, PointerEvent as ReactPointerEvent } from 'react'
import { Button, FlexLayout, H2, Input, Text } from '@salt-ds/core'
import { useEffect, useState } from 'react'

import type { DecisionKind, ItemRow, WorkflowFieldView } from '../api'
import { DecisionCard } from './DecisionCard'

interface Props {
  rows: ItemRow[]
  fields: WorkflowFieldView[]
  terminalLabels: Record<string, string>
  busyKey: string | null
  undoBusy: boolean
  canUndo: boolean
  error: string | null
  announcement: string
  /** False while the detail panel is open, so keys do not decide behind it. */
  enabled: boolean
  onDecide: (key: string, decision: DecisionKind, reason?: string) => void
  onUndo: () => void
  onOpen: (key: string) => void
  onShowList: (decision: string) => void
  onReload: () => void
  reloading: boolean
}

interface DragState {
  key: string
  startX: number
  startY: number
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
  busyKey,
  undoBusy,
  canUndo,
  error,
  announcement,
  enabled,
  onDecide,
  onUndo,
  onOpen,
  onShowList,
  onReload,
  reloading,
}: Props): JSX.Element {
  const [drag, setDrag] = useState<DragState | null>(null)
  const [reason, setReason] = useState<{ key: string; text: string } | null>(null)
  const top = rows[0]
  const busy = busyKey !== null || undoBusy
  const canAct = enabled && top !== undefined && !busy
  const reasonOpen = top !== undefined && reason?.key === top.key
  const reasonText =
    reason !== null && top !== undefined && reason.key === top.key ? reason.text : ''

  useEffect(() => {
    if (!enabled || top === undefined) return
    const onKey = (event: KeyboardEvent): void => {
      const target = event.target
      if (
        target instanceof HTMLElement &&
        ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'A'].includes(target.tagName)
      ) {
        return
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (event.key === 'ArrowRight' && !busy) {
        event.preventDefault()
        onDecide(top.key, 'accept')
      } else if (event.key === 'ArrowLeft' && !busy) {
        event.preventDefault()
        onDecide(top.key, 'reject')
      } else if ((event.key === 'u' || event.key === 'U') && canUndo && !busy) {
        onUndo()
      } else if (event.key === 'Enter' && !busy) {
        onOpen(top.key)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled, top, busy, canUndo, onDecide, onUndo, onOpen])

  const dragging = drag !== null && top !== undefined && drag.key === top.key
  const limit = drag === null ? 1 : threshold(drag.width)
  const ratio = dragging && drag !== null ? Math.min(1, Math.abs(drag.dx) / limit) : 0
  const direction: DecisionKind | null =
    !dragging || drag === null || Math.abs(drag.dx) < 8
      ? null
      : drag.dx > 0
        ? 'accept'
        : 'reject'

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>): void {
    if (!canAct || top === undefined || event.button !== 0) return
    const target = event.target
    if (target instanceof HTMLElement && target.closest('button, a, input')) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setDrag({
      key: top.key,
      startX: event.clientX,
      startY: event.clientY,
      dx: 0,
      width: event.currentTarget.clientWidth,
    })
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>): void {
    if (!dragging || drag === null) return
    const dx = event.clientX - drag.startX
    setDrag({ ...drag, dx })
  }

  function handlePointerUp(): void {
    if (!dragging || drag === null || top === undefined) {
      setDrag(null)
      return
    }
    if (Math.abs(drag.dx) >= threshold(drag.width)) {
      onDecide(top.key, drag.dx > 0 ? 'accept' : 'reject')
    }
    setDrag(null)
  }

  function rejectWithoutReason(): void {
    setReason(null)
    if (top !== undefined) onDecide(top.key, 'reject')
  }

  function rejectWithReason(): void {
    const text = reasonText.trim()
    setReason(null)
    if (top !== undefined) onDecide(top.key, 'reject', text || undefined)
  }

  return (
    <section className="deck" aria-label="Review deck">
      <FlexLayout className="deck-toolbar" justify="space-between" align="center" gap={2}>
        <Text className="deck-count">
          {rows.length === 0 ? 'Nothing to review' : `${rows.length} to review`}
        </Text>
        <FlexLayout gap={2} align="center">
          {canUndo ? (
            <Button appearance="bordered" onClick={onUndo} disabled={busy}>
              Undo last
            </Button>
          ) : null}
          <Button appearance="bordered" onClick={onReload} disabled={reloading}>
            Reload
          </Button>
        </FlexLayout>
      </FlexLayout>

      <p className="deck-announcement" aria-live="polite">
        {announcement}
      </p>

      {error ? (
        <div className="deck-error" role="alert">
          {error}
        </div>
      ) : null}

      {top === undefined ? (
        <div className="deck-empty">
          <H2>All caught up</H2>
          <Text color="secondary">
            No deviations are waiting for a decision. Accepted items are queued for the
            submitter; rejected items stay visible in the list.
          </Text>
          <FlexLayout gap={2} wrap>
            <Button appearance="bordered" onClick={() => onShowList('accept')}>
              View accepted
            </Button>
            <Button appearance="bordered" onClick={() => onShowList('reject')}>
              View rejected
            </Button>
          </FlexLayout>
        </div>
      ) : (
        <>
          <div className="deck-stack">
            {rows.slice(0, 3).map((row, index) => {
              const isTop = index === 0
              const style =
                isTop && drag !== null
                  ? {
                      transform: `translateX(${drag.dx}px) rotate(${drag.dx / 24}deg)`,
                    }
                  : undefined
              return (
                <div
                  key={row.key}
                  className="deck-slot"
                  data-offset={index}
                  data-dragging={isTop && drag !== null ? 'true' : undefined}
                  style={style}
                  onPointerDown={isTop ? handlePointerDown : undefined}
                  onPointerMove={isTop ? handlePointerMove : undefined}
                  onPointerUp={isTop ? handlePointerUp : undefined}
                  onPointerCancel={isTop ? () => setDrag(null) : undefined}
                >
                  <DecisionCard
                    row={row}
                    fields={fields}
                    terminalLabels={terminalLabels}
                    offset={index}
                    onDetails={() => onOpen(row.key)}
                  />
                  {isTop && direction !== null ? (
                    <div className="swipe-stamp" data-kind={direction} style={{ opacity: ratio }} aria-hidden>
                      {direction === 'accept' ? 'ACCEPT' : 'REJECT'}
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>

          {reasonOpen ? (
            <div className="deck-reason">
              <Input
                value={reasonText}
                inputProps={{
                  onChange: (event) =>
                    setReason((current) =>
                      current === null ? current : { ...current, text: event.target.value },
                    ),
                  placeholder: 'Reason (optional)',
                  'aria-label': 'Reject reason',
                  onKeyDown: (event) => {
                    if (event.key === 'Enter') rejectWithReason()
                    if (event.key === 'Escape') setReason(null)
                  },
                }}
              />
              <Button appearance="bordered" onClick={rejectWithReason} disabled={busy}>
                Reject
              </Button>
              <Button appearance="transparent" onClick={() => setReason(null)}>
                Cancel
              </Button>
            </div>
          ) : null}

          <div className="deck-actions">
            <Button
              appearance="bordered"
              className="reject-button"
              disabled={!canAct}
              onClick={
                reasonOpen
                  ? rejectWithoutReason
                  : () => {
                      if (top !== undefined) setReason({ key: top.key, text: '' })
                    }
              }
              aria-label={reasonOpen ? 'Reject without reason' : `Reject ${top.key}`}
            >
              {reasonOpen ? 'Reject without reason' : 'Reject'}
            </Button>
            <Button
              appearance="solid"
              className="accept-button"
              disabled={!canAct}
              onClick={() => onDecide(top.key, 'accept')}
              aria-label={`Accept ${top.key}`}
            >
              Accept
            </Button>
          </div>

          <Text color="secondary" className="deck-help">
            Swipe the card, use the buttons, or press ← / →. Every decision is reversible with
            Undo.
          </Text>
        </>
      )}
    </section>
  )
}
