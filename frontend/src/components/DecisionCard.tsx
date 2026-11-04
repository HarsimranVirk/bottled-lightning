/**
 * One deviation card, matching the legacy deck: record link, approval date, the pages
 * that will be updated, the raw description, ROI details and the four editable values.
 *
 * Presentational only: the deck owns the draft, decisions and the exit animation.
 */

import type { JSX } from 'react'
import { Button, Card, CardContent, FlexLayout, Input, Link, StackLayout, Text } from '@salt-ds/core'

import type { ItemDetail, ItemRow, WorkflowFieldView } from '../api'
import { draftDisplay, orderedFields } from '../format'
import { StatusChip } from './StatusChip'

const REF_LABELS: Record<string, string> = {
  opportunity: 'Opportunity',
  cl_contract: 'CL Contract',
  collateral: 'Collateral',
  lms2_collateral: 'LMS2 Collateral',
  lms2_cl_contract: 'LMS2 CL Contract',
}

const REF_ORDER = ['opportunity', 'cl_contract', 'collateral', 'lms2_collateral', 'lms2_cl_contract']

const ROI_FIELDS: { key: string; label: string }[] = [
  { key: 'requested_roi', label: 'Requested ROI' },
  { key: 'ideal_roi', label: 'Ideal ROI' },
  { key: 'updated_roi', label: 'Updated ROI (in LMS)' },
  { key: 'requested_variance', label: 'Requested Variance' },
]

interface Props {
  row: ItemRow
  fields: WorkflowFieldView[]
  terminalLabels: Record<string, string>
  detail: ItemDetail | null
  values: Record<string, string>
  /** 0 is the top card; 1-2 are the peeks behind it. */
  offset: number
  leavingClass: string | null
  onField: (key: string, value: string) => void
  onDetails: () => void
}

export function DecisionCard({
  row,
  fields,
  terminalLabels,
  detail,
  values,
  offset,
  leavingClass,
  onField,
  onDetails,
}: Props): JSX.Element {
  const ordered = orderedFields(fields)
  const missing = ordered.filter((field) => (values[field.key] ?? '').trim() === '').length
  const description = detail?.attributes.description ?? null
  const refRank = (kind: string): number => {
    const index = REF_ORDER.indexOf(kind)
    return index === -1 ? REF_ORDER.length : index
  }
  const refs = [...(detail?.refs ?? [])].sort(
    (left, right) => refRank(left.kind) - refRank(right.kind),
  )

  return (
    <Card elevation="raised" className={`deck-stack deck-card ${leavingClass ?? ''}`}>
      <CardContent>
        <StackLayout gap={1}>
          <FlexLayout justify="space-between" align="center">
            <FlexLayout gap={2} align="center">
              {row.recordUrl ? (
                <Link href={row.recordUrl} target="_blank" className="deck-title-link">
                  {row.key}
                </Link>
              ) : (
                <Text className="deck-title-link">{row.key}</Text>
              )}
              <StatusChip status={row.status} labels={terminalLabels} />
            </FlexLayout>
            <Button appearance="transparent" onClick={onDetails}>
              Details
            </Button>
          </FlexLayout>

          {row.approvedAt ? (
            <Text color="secondary" styleAs="label">
              SF approval date: {row.approvedAt}
            </Text>
          ) : null}

          {row.reason ? (
            <Text color="error" styleAs="label">
              {row.reason}
            </Text>
          ) : null}

          {refs.length > 0 ? (
            <StackLayout gap={0.5}>
              <Text color="secondary" styleAs="label">
                Pages to update
              </Text>
              <StackLayout gap={0.5} className="deck-refs" data-no-swipe>
                {refs.map((ref) => (
                  <FlexLayout key={ref.kind} gap={1} align="center">
                    <Text styleAs="label" color="secondary" className="deck-ref-label">
                      {REF_LABELS[ref.kind] ?? ref.kind}
                    </Text>
                    <Link href={ref.url} target="_blank">
                      {ref.name}
                    </Link>
                  </FlexLayout>
                ))}
              </StackLayout>
            </StackLayout>
          ) : null}

          <Text color="secondary" styleAs="label">
            Loan Deviation Description — read it, raw is truth
          </Text>
          <div className="deck-description" data-no-swipe>
            {detail === null ? (
              <Text color="secondary">loading description…</Text>
            ) : description ? (
              <Text styleAs="code" className="deck-description-text">
                {description}
              </Text>
            ) : (
              <Text color="secondary">no description picked yet — run an extraction first</Text>
            )}
          </div>

          <Text color="secondary" styleAs="label">
            Housing Loan Deviation Details
          </Text>
          <div className="deck-roi" data-no-swipe>
            {ROI_FIELDS.map((field) => (
              <StackLayout gap={0} key={field.key}>
                <Text color="secondary" styleAs="label">
                  {field.label}
                </Text>
                <Text>{detail?.attributes[field.key] ?? '—'}</Text>
              </StackLayout>
            ))}
          </div>

          <Text color="secondary" styleAs="label">
            New loan parameters to populate — prefilled where the parser could read the
            description; correct anything it got wrong:
          </Text>
          <StackLayout gap={1}>
            {ordered.map((field) => (
              <FlexLayout key={field.key} gap={2} align="center" className="deck-field">
                <Text styleAs="label" color="secondary" className="deck-field-label">
                  {field.label}
                </Text>
                <Input
                  value={draftDisplay(field, values[field.key] ?? '')}
                  inputProps={{
                    inputMode: field.valueType === 'text' ? undefined : 'numeric',
                    'aria-label': field.label,
                    onChange: (event) => {
                      const raw = event.target.value
                      onField(
                        field.key,
                        field.valueType === 'text' ? raw : raw.replace(/[^\d]/g, ''),
                      )
                    },
                  }}
                />
              </FlexLayout>
            ))}
          </StackLayout>

          {missing > 0 ? (
            <Text styleAs="label" className="deck-warning">
              {missing} {missing === 1 ? 'value is' : 'values are'} missing — check the
              description before accepting.
            </Text>
          ) : null}

          {offset === 0 ? (
            <Text color="secondary" styleAs="label">
              ← skip · → accept · swipe the card or use the buttons
            </Text>
          ) : null}
        </StackLayout>
      </CardContent>
    </Card>
  )
}
