/**
 * One deviation card, matching the legacy deck: record link, approval date, the pages
 * that will be updated, the raw description, ROI details and the four editable values.
 *
 * Presentational only: the deck owns the draft, decisions and the exit animation.
 */

import type { JSX } from 'react'
import {
  Banner,
  BannerContent,
  Card,
  CardContent,
  FlexLayout,
  FormField,
  FormFieldLabel,
  GridLayout,
  Input,
  Link,
  Panel,
  StackLayout,
  Text,
} from '@salt-ds/core'

import type { ItemDetail, ItemRow, WorkflowFieldView } from '../api'
import { absoluteUrl, draftDisplay, orderedFields } from '../format'
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
  /** Used to turn a legacy relative record href into an absolute Salesforce URL. */
  listUrl: string
  onField: (key: string, value: string) => void
}

export function DecisionCard({
  row,
  fields,
  terminalLabels,
  detail,
  values,
  listUrl,
  onField,
}: Props): JSX.Element {
  const ordered = orderedFields(fields)
  const missing = ordered.filter((field) => (values[field.key] ?? '').trim() === '').length
  const description = detail?.attributes.description ?? null
  const recordHref = row.recordUrl ? absoluteUrl(row.recordUrl, listUrl) : null
  const refRank = (kind: string): number => {
    const index = REF_ORDER.indexOf(kind)
    return index === -1 ? REF_ORDER.length : index
  }
  const refs = [...(detail?.refs ?? [])].sort(
    (left, right) => refRank(left.kind) - refRank(right.kind),
  )

  return (
    <Card elevation="raised" className="deck-card">
      <CardContent>
        <StackLayout gap={1}>
          <FlexLayout gap={2} align="center">
            {recordHref ? (
              <Link href={recordHref} target="_blank">
                {row.key}
              </Link>
            ) : (
              <Text>{row.key}</Text>
            )}
            <StatusChip status={row.status} labels={terminalLabels} />
          </FlexLayout>

          <Text color="secondary" styleAs="label">
            SF approval date: {row.approvedAt ?? '—'}
          </Text>

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
              <GridLayout columns={{ xs: 1, sm: 2 }} gap={0.5}>
                {refs.map((ref) => (
                  <FlexLayout key={ref.kind} gap={1} align="center">
                    <Text styleAs="label" color="secondary">
                      {REF_LABELS[ref.kind] ?? ref.kind}
                    </Text>
                    <Link href={ref.url} target="_blank">
                      {ref.name}
                    </Link>
                  </FlexLayout>
                ))}
              </GridLayout>
            </StackLayout>
          ) : null}

          <Text color="secondary" styleAs="label">
            Loan Deviation Description — read it, raw is truth
          </Text>
          <Panel className="deck-description">
            {detail === null ? (
              <Text color="secondary">loading description…</Text>
            ) : description ? (
              <Text styleAs="code" className="deck-description-text">
                {description}
              </Text>
            ) : (
              <Text color="secondary">no description picked yet — run an extraction first</Text>
            )}
          </Panel>

          <Text color="secondary" styleAs="label">
            Housing Loan Deviation Details
          </Text>
          <GridLayout columns={{ xs: 1, sm: 2 }} gap={1}>
            {ROI_FIELDS.map((field) => (
              <StackLayout gap={0} key={field.key}>
                <Text color="secondary" styleAs="label">
                  {field.label}
                </Text>
                <Text>{detail?.attributes[field.key] ?? '—'}</Text>
              </StackLayout>
            ))}
          </GridLayout>

          <Text color="secondary" styleAs="label">
            New loan parameters to populate — prefilled where the parser could read the
            description; correct anything it got wrong:
          </Text>
          <StackLayout gap={1}>
            {ordered.map((field) => (
              <FormField key={field.key} labelPlacement="left">
                <FormFieldLabel>{field.label}</FormFieldLabel>
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
              </FormField>
            ))}
          </StackLayout>

          {missing > 0 ? (
            <Banner status="warning">
              <BannerContent>
                {missing} {missing === 1 ? 'value is' : 'values are'} missing — check the
                description before accepting.
              </BannerContent>
            </Banner>
          ) : null}
        </StackLayout>
      </CardContent>
    </Card>
  )
}
