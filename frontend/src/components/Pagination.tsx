/** Shared table pagination built from Salt buttons, text and a rows-per-page dropdown. */

import type { JSX } from 'react'
import {
  Button,
  Dropdown,
  FlexLayout,
  FormField,
  FormFieldLabel,
  Option,
  Text,
} from '@salt-ds/core'

interface Props {
  page: number
  size: number
  total: number
  onPage: (page: number) => void
  onSize: (size: number) => void
  sizes?: number[]
}

export function Pagination({
  page,
  size,
  total,
  onPage,
  onSize,
  sizes = [10, 25, 50, 100],
}: Props): JSX.Element {
  const pages = Math.max(1, Math.ceil(total / size))
  const from = total === 0 ? 0 : (page - 1) * size + 1
  const to = Math.min(total, page * size)

  return (
    <FlexLayout justify="space-between" align="center" gap={2} wrap className="pagination">
      <Text color="secondary" styleAs="label">
        {from}–{to} of {total}
      </Text>
      <FlexLayout gap={1} align="center">
        <Button appearance="bordered" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </Button>
        <Text color="secondary" styleAs="label">
          Page {page} of {pages}
        </Text>
        <Button
          appearance="bordered"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          Next
        </Button>
      </FlexLayout>
      <FormField labelPlacement="left" className="pagination-rows">
        <FormFieldLabel>Rows</FormFieldLabel>
        <Dropdown
          value={String(size)}
          selected={[String(size)]}
          onSelectionChange={(_event, selected) => onSize(Number(selected[0] ?? size))}
        >
          {sizes.map((value) => (
            <Option key={value} value={String(value)}>
              {value}
            </Option>
          ))}
        </Dropdown>
      </FormField>
    </FlexLayout>
  )
}
