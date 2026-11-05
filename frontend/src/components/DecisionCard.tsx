/**
 * One deviation card, matching the legacy deck: record link, approval date, the pages
 * that will be updated, the raw description, ROI details and the four editable values.
 *
 * Presentational only: the deck owns the draft, decisions and the exit animation.
 */

import type { JSX } from 'react'
import { useState } from 'react'
import {
  Button,
  Card,
  CardContent,
  Dialog,
  DialogCloseButton,
  DialogContent,
  DialogHeader,
  FlexLayout,
  FormField,
  FormFieldLabel,
  GridLayout,
  Input,
  Link,
  StackLayout,
  Text,
} from '@salt-ds/core'

import type { ItemDetail, ItemRow, WorkflowFieldView } from '../api'
import { absoluteUrl, draftDisplay, orderedFields } from '../format'
import { useIsNarrow } from '../useIsNarrow'
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

function splitParameters(text: string): { old: string; new: string } | null {
  const match = text.match(/(^|\n)(\s*New\s+Param[\s\S]*)$/i)
  if (match === null) return null
  const old = text.slice(0, match.index).trim()
  if (!old) return null
  return { old, new: match[2].trim() }
}

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
  const description = detail?.attributes.description ?? null
  const descriptionParts = description === null ? null : splitParameters(description)
  // Long descriptions flow into newspaper columns so the whole text stays visible
  // without scrolling; short Old/New pairs keep their block-aligned columns.
  const descriptionInColumns = description !== null && description.length > 500
  const descriptionLines = description === null ? 0 : description.split('\n').length
  const descriptionInFourColumns = descriptionInColumns && descriptionLines > 30
  const narrow = useIsNarrow()
  const [openDescription, setOpenDescription] = useState(false)
  // Above these limits the card cannot fit the viewport; show the compact form
  // (New block or a preview) and open the full raw text in a Salt dialog.
  const oversized = description !== null && (description.length > 1200 || descriptionLines > 40)
  const compactDescription = oversized || narrow
  const previewBody =
    description === null
      ? ''
      : descriptionParts !== null
        ? descriptionParts.new
        : description
  const previewText = previewBody.slice(0, narrow ? 220 : 240)
  const previewCut = previewBody.length > previewText.length
  const needsDialog =
    compactDescription && description !== null && (descriptionParts !== null || previewCut)
  const recordHref = row.recordUrl ? absoluteUrl(row.recordUrl, listUrl) : null
  const refRank = (kind: string): number => {
    const index = REF_ORDER.indexOf(kind)
    return index === -1 ? REF_ORDER.length : index
  }
  const refs = [...(detail?.refs ?? [])].sort(
    (left, right) => refRank(left.kind) - refRank(right.kind),
  )

  return (
    <>
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

          <Text color="secondary" styleAs="label">
            Loan Deviation Description — read it, raw is truth
          </Text>
          <Card variant="secondary" elevation="flat" className="deck-description">
            {detail === null ? (
              <Text color="secondary">loading description…</Text>
            ) : description === null ? (
              <Text color="secondary">no description picked yet — run an extraction first</Text>
            ) : compactDescription ? (
              <StackLayout gap={0.5}>
                <Text styleAs="code" className="deck-description-text">
                  {previewText}
                  {previewCut ? '…' : ''}
                </Text>
                {needsDialog ? (
                  <Button appearance="transparent" onClick={() => setOpenDescription(true)}>
                    Read full description
                  </Button>
                ) : null}
              </StackLayout>
            ) : descriptionInColumns ? (
              <Text
                styleAs="code"
                className={`deck-description-text deck-description-columns${
                  descriptionInFourColumns ? ' deck-description-columns-4' : ''
                }`}
              >
                {description}
              </Text>
            ) : descriptionParts ? (
              <GridLayout columns={{ xs: 1, md: 2 }} gap={2}>
                <Text styleAs="code" className="deck-description-text">
                  {descriptionParts.old}
                </Text>
                <Text styleAs="code" className="deck-description-text">
                  {descriptionParts.new}
                </Text>
              </GridLayout>
            ) : (
              <Text styleAs="code" className="deck-description-text">
                {description}
              </Text>
            )}
          </Card>

          <GridLayout columns={{ xs: 1, lg: "1fr 1fr" }} gap={2}>
            <StackLayout gap={2}>
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

              <StackLayout gap={1}>
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
              </StackLayout>
            </StackLayout>

            <StackLayout gap={1}>
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
            </StackLayout>
          </GridLayout>
        </StackLayout>
      </CardContent>
    </Card>
    {needsDialog ? (
      <Dialog open={openDescription} onOpenChange={setOpenDescription} size="large">
        <DialogHeader
          header="Loan Deviation Description"
          actions={<DialogCloseButton onClick={() => setOpenDescription(false)} />}
        />
        <DialogContent>
          <div className="deck-description-dialog">
            <Text styleAs="code" className="deck-description-text">
              {description}
            </Text>
          </div>
        </DialogContent>
      </Dialog>
    ) : null}
    </>
  )
}
