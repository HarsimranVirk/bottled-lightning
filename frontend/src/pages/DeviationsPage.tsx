/** The workflow list + item detail route. Owns every query for this screen. */

import type { JSX } from 'react'
import { Button, FlexLayout, H1, Input, Spinner, Text } from '@salt-ds/core'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { rememberWorkflows } from '../api'
import { ItemDrawer } from '../components/ItemDrawer'
import { ItemsGrid } from '../components/ItemsGrid'
import { useItem, useItems, useSync, useWorkflows } from '../queries'

const Z02_WORKFLOW = 'deviations_z02'

export function DeviationsPage(): JSX.Element {
  const { key } = useParams()
  const navigate = useNavigate()
  const workflows = useWorkflows()
  // The Z02 tab is concrete; the registry only supplies labels and fields.
  const workflow = workflows.data?.find((item) => item.name === Z02_WORKFLOW) ?? workflows.data?.[0]
  const [status, setStatus] = useState('')
  const [query, setQuery] = useState('')

  useEffect(() => {
    if (workflows.data) rememberWorkflows(workflows.data)
  }, [workflows.data])

  const sync = useSync(workflow?.route ?? null)
  const items = useItems(workflow?.route ?? null, status, query)
  const detail = useItem(workflow?.route ?? null, key ?? null)

  if (workflows.isLoading) return <Spinner />
  if (!workflow) return <Text>The Deviations Z02 workflow is not registered.</Text>

  return (
    <FlexLayout direction="column" gap={4}>
      <FlexLayout justify="space-between" align="center">
        <H1>{workflow.label}</H1>
        <Text color="secondary">
          {sync.data ? `${sync.data.rowsRead} rows in the last refresh` : 'no refresh yet'}
        </Text>
      </FlexLayout>

      <FlexLayout gap={2} align="end" className="filters">
        <label>
          <Text>Status</Text>
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filter by status">
            <option value="">All</option>
            {['present', 'ready', 'editing', 'submitting', 'needs_review', 'completed', 'closed', 'skipped'].map(
              (option) => (
                <option key={option} value={option}>
                  {option.replace(/_/g, ' ')}
                </option>
              ),
            )}
          </select>
        </label>
        <label>
          <Text>Search</Text>
          <Input value={query} inputProps={{ onChange: (event) => setQuery(event.target.value) }} placeholder="Deviation number" />
        </label>
        <Button appearance="bordered" onClick={() => void items.refetch()} disabled={items.isFetching}>
          Reload
        </Button>
      </FlexLayout>

      {items.isLoading ? <Spinner /> : null}
      {items.error ? <Text className="reason">{items.error.message}</Text> : null}
      {items.data && items.data.rows.length === 0 ? (
        <Text color="secondary">No items match. Clear the filters or refresh the list.</Text>
      ) : null}
      {items.data && items.data.rows.length > 0 ? (
        <ItemsGrid
          rows={items.data.rows}
          fields={workflow.fields}
          terminalLabels={workflow.terminalLabels}
          onOpen={(itemKey) => navigate(`/deviations-z02/${encodeURIComponent(itemKey)}`)}
        />
      ) : null}

      {key ? (
        detail.data ? (
          <ItemDrawer
            detail={detail.data}
            fields={workflow.fields}
            refKinds={workflow.refKinds}
            terminalLabels={workflow.terminalLabels}
            onClose={() => navigate('/deviations-z02')}
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
