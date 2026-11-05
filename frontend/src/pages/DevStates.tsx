/**
 * State harness (Slice A acceptance): renders every state-matrix row from fixtures, so
 * each row can be screenshotted and reviewed without Salesforce.
 */

import type { JSX } from 'react'
import { FlexLayout, H1, H2, Panel, Spinner, StackLayout, Text } from '@salt-ds/core'
import { Link } from 'react-router-dom'

import type { ItemDetail, ItemRow, JobView, SessionView, SyncView, WorkflowFieldView } from '../api'
import { DecisionDeck } from '../components/DecisionDeck'
import { ItemDrawer } from '../components/ItemDrawer'
import { HistoryTable } from '../components/HistoryTable'
import { JobsPanel } from '../components/JobsPanel'
import { StatusChip } from '../components/StatusChip'
import { SyncBanner } from '../components/SyncBanner'

const FIELDS: WorkflowFieldView[] = [
  { key: 'loan_amount', label: 'Loan Amount', valueType: 'amount', required: false, targets: ['cl_contract'] },
  { key: 'property_value', label: 'Property Value', valueType: 'amount', required: false, targets: ['collateral'] },
  { key: 'tenure', label: 'Tenure', valueType: 'months', required: false, targets: ['cl_contract'] },
  { key: 'emi_incl_hffc', label: 'EMI incl. HFFC', valueType: 'amount', required: false, targets: ['cl_contract'] },
]
const REF_KINDS = ['opportunity', 'cl_contract', 'collateral', 'lms2_cl_contract', 'lms2_collateral']
const TERMINAL_LABELS = { completed: 'Implemented' }

const STATUSES = [
  'present',
  'extracting',
  'ready',
  'editing',
  'submitting',
  'applying',
  'validating',
  'executing',
  'needs_review',
  'completed',
  'closed',
  'skipped',
]

function row(status: string, key = 'Deviation-03112026-486382'): ItemRow {
  return {
    key,
    status,
    present: !['completed', 'closed'].includes(status),
    epoch: 1,
    recordUrl: 'https://example/record',
    approvedAt: '4/11/2026 6:46 pm',
    reason: status === 'skipped' ? 'multiple lms2 cl contract (2)' : null,
    fields: {
      loan_amount: { extracted: '13,00,000', lastSynced: '13,00,000', proposed: null, applied: null, status: 'extracted' },
      property_value: { extracted: '22,50,000', lastSynced: '22,50,000', proposed: null, applied: null, status: 'extracted' },
      tenure: { extracted: null, lastSynced: null, proposed: null, applied: null, status: 'extracted' },
      emi_incl_hffc: { extracted: '16,256', lastSynced: '16,256', proposed: null, applied: null, status: 'extracted' },
    },
    decision: null,
    activeJob:
      status === 'submitting'
        ? {
            id: 9,
            workflow: 'deviations_z02',
            item: key,
            kind: 'submit',
            status: 'running',
            phase: 'apply',
            attempts: 1,
            leaseOwner: 'w0',
            createdAt: '2026-11-04T18:00:00Z',
            startedAt: '2026-11-04T18:00:01Z',
            finishedAt: null,
            error: null,
          }
        : null,
  }
}

function detail(status: string): ItemDetail {
  return {
    ...row(status),
    attributes: {
      description: 'Old Paramaters\nLA-13,00,000\nPP-22,50,000\nEmIs & other fixed pmts inc HFFC Loan-16,256',
      requested_roi: null,
      ideal_roi: '13.25%',
      updated_roi: null,
      requested_variance: null,
      product_type: 'Home Loan (Resale)',
    },
    refs: [
      { kind: 'opportunity', name: 'Shaban Khan', url: 'https://example/opp' },
      { kind: 'cl_contract', name: 'LAI-00533155', url: 'https://example/cl' },
      { kind: 'collateral', name: 'CJID-0000280688', url: 'https://example/coll' },
    ],
    edits: [{ field: 'tenure', oldValue: null, newValue: '240', at: '2026-11-04T18:05:00Z' }],
    decisions: [{ decision: 'accept', reason: null, at: '2026-11-04T18:20:00Z' }],
  }
}

const SESSIONS: Record<string, SessionView> = {
  none: { state: 'none', paused: false, cookies: null, savedAt: null, lastEvent: null },
  valid: { state: 'valid', paused: false, cookies: 34, savedAt: '2026-11-04T15:20:40Z', lastEvent: null },
  expired: { state: 'expired', paused: true, cookies: 34, savedAt: '2026-11-03T09:00:00Z', lastEvent: null },
}

const VALID_SYNC: SyncView = {
  workflow: 'deviations_z02',
  capturedAt: '2026-11-04T18:00:00Z',
  headerTotal: 7,
  rowsRead: 7,
  valid: true,
  warning: null,
  added: 0,
  updated: 7,
  closed: 0,
}

const INVALID_SYNC: SyncView = { ...VALID_SYNC, headerTotal: 8, rowsRead: 7, valid: false, warning: 'header total 8 != rows 7' }

const JOBS: JobView[] = [
  {
    id: 9,
    workflow: 'deviations_z02',
    item: 'Deviation-03112026-486382',
    kind: 'submit',
    status: 'running',
    phase: 'apply',
    durationMs: 4200,
    attempts: 1,
    leaseOwner: 'w0',
    createdAt: '2026-11-04T18:00:00Z',
    startedAt: '2026-11-04T18:00:01Z',
    finishedAt: null,
    error: null,
  },
  {
    id: 8,
    workflow: 'deviations_z02',
    item: 'Deviation-04112026-486814',
    kind: 'extract',
    status: 'failed',
    phase: 'extract',
    durationMs: 1000,
    attempts: 2,
    leaseOwner: null,
    createdAt: '2026-11-04T17:00:00Z',
    startedAt: '2026-11-04T17:00:01Z',
    finishedAt: '2026-11-04T17:00:30Z',
    error: 'LeaseHeld: cannot close while a job lease is held',
  },
]

function Section({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
  return (
    <Panel>
      <StackLayout gap={1}>
        <H2>{title}</H2>
        {children}
      </StackLayout>
    </Panel>
  )
}

export function DevStates(): JSX.Element {
  return (
    <FlexLayout direction="column" gap={4}>
      <H1>State harness</H1>
      <Text color="secondary">Fixtures only. Screenshot at 390 / 768 / 1280 for review.</Text>
      <Link to="/dev/db">Open the DB explorer</Link>

      <Section title="Status chips">
        <FlexLayout gap={1} wrap>
          {STATUSES.map((status) => (
            <StatusChip key={status} status={status} labels={TERMINAL_LABELS} />
          ))}
        </FlexLayout>
      </Section>

      <Section title="Banners">
        <FlexLayout direction="column" gap={2}>
          <SyncBanner session={SESSIONS.none} sync={undefined} onLogin={() => {}} onRefresh={() => {}} refreshing={false} />
          <SyncBanner session={SESSIONS.valid} sync={VALID_SYNC} onLogin={() => {}} onRefresh={() => {}} refreshing={false} />
          <SyncBanner session={SESSIONS.expired} sync={VALID_SYNC} onLogin={() => {}} onRefresh={() => {}} refreshing={false} />
          <SyncBanner session={SESSIONS.valid} sync={INVALID_SYNC} onLogin={() => {}} onRefresh={() => {}} refreshing={false} />
        </FlexLayout>
      </Section>

      <Section title="History (accepted)">
        <HistoryTable
          rows={[
            {
              ...row('ready', 'Deviation-03112026-486382'),
              decision: { decision: 'accept', reason: null, at: '2026-11-04T18:20:00Z' },
            },
            {
              ...row('completed', 'Deviation-04112026-486814'),
              decision: { decision: 'accept', reason: null, at: '2026-11-04T17:05:00Z' },
            },
          ]}
          fields={FIELDS}
          terminalLabels={TERMINAL_LABELS}
          listUrl="https://example.lightning.force.com/lightning/o/Deviation/list"
          query=""
          onQuery={() => {}}
          page={1}
          size={25}
          total={2}
          onPage={() => {}}
          onSize={() => {}}
          loading={false}
          onOpen={() => {}}
        />
      </Section>

      <Section title="Loading / empty">
        <Spinner />
        <Text color="secondary">No items match. Clear the filters or refresh the list.</Text>
      </Section>

      <Section title="Detail: ready">
        <ItemDrawer detail={detail('ready')} fields={FIELDS} refKinds={REF_KINDS} terminalLabels={TERMINAL_LABELS} onClose={() => {}} />
      </Section>

      <Section title="Detail: needs review">
        <ItemDrawer
          detail={{ ...detail('needs_review'), reason: 'submission job failed; review and retry' }}
          fields={FIELDS}
          refKinds={REF_KINDS}
          terminalLabels={TERMINAL_LABELS}
          onClose={() => {}}
        />
      </Section>

      <Section title="Detail: implemented">
        <ItemDrawer detail={detail('completed')} fields={FIELDS} refKinds={REF_KINDS} terminalLabels={TERMINAL_LABELS} onClose={() => {}} />
      </Section>

      <Section title="Review deck: card">
        <DecisionDeck
          rows={[
            row('ready', 'Deviation-03112026-486382'),
            row('needs_review', 'Deviation-04112026-486814'),
            row('editing', 'Deviation-05112026-486901'),
          ]}
          fields={FIELDS}
          terminalLabels={{ completed: 'Implemented' }}
          detail={detail('ready')}
          tally={{ accept: 2, skip: 1, pending: 3 }}
          error={null}
          announcement=""
          listUrl="https://example.lightning.force.com/lightning/o/Deviation/list"
          onDecide={async () => true}
          onReplay={() => {}}
          replaying={false}
          onHistory={() => {}}
          onRefresh={() => {}}
          refreshing={false}
        />
      </Section>

      <Section title="Review deck: complete">
        <DecisionDeck
          rows={[]}
          fields={FIELDS}
          terminalLabels={{}}
          detail={null}
          tally={{ accept: 4, skip: 2, pending: 0 }}
          error={null}
          announcement="Accepted Deviation-03112026-486382 · deck complete"
          listUrl="https://example.lightning.force.com/lightning/o/Deviation/list"
          onDecide={async () => true}
          onReplay={() => {}}
          replaying={false}
          onHistory={() => {}}
          onRefresh={() => {}}
          refreshing={false}
        />
      </Section>

      <Section title="Review deck: decision failed">
        <DecisionDeck
          rows={[row('ready', 'Deviation-03112026-486382')]}
          fields={FIELDS}
          terminalLabels={{}}
          detail={detail('ready')}
          tally={{ accept: 0, skip: 0, pending: 1 }}
          error="item is submitting and not decidable"
          announcement=""
          listUrl="https://example.lightning.force.com/lightning/o/Deviation/list"
          onDecide={async () => false}
          onReplay={() => {}}
          replaying={false}
          onHistory={() => {}}
          onRefresh={() => {}}
          refreshing={false}
        />
      </Section>

      <Section title="Jobs">
        <JobsPanel
          jobs={JOBS}
          total={JOBS.length}
          filters={{
            id: '',
            status: '',
            kind: '',
            phase: '',
            item: '',
            error: '',
            startedAfter: '',
            startedBefore: '',
            durationMinS: '',
            durationMaxS: '',
          }}
          onFilters={() => {}}
          sort="id"
          order="desc"
          onSort={() => {}}
          page={1}
          size={25}
          onPage={() => {}}
          onSize={() => {}}
          selected={8}
          logs={{ job: JOBS[1], logs: ['extract start: …', 'failed: LeaseHeld'] }}
          loadingLogs={false}
          onSelect={() => {}}
          loading={false}
        />
      </Section>
    </FlexLayout>
  )
}
