import type { ReactNode } from 'react'
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  StackLayout,
  FlexLayout,
  Text,
  Divider,
  Spinner,
  StatusIndicator,
} from '@salt-ds/core'
import {
  CookieSolidIcon,
  RefreshIcon,
  ClockIcon,
  UserSolidIcon,
} from '@salt-ds/icons'
import { formatAge } from '../shared'
import type { SessionInfo } from '../types'

interface InfoRowProps {
  icon?: ReactNode
  label: string
  children: ReactNode
}

function InfoRow({ icon, label, children }: InfoRowProps) {
  return (
    <FlexLayout gap={2} align="center">
      <Text color="secondary" styleAs="label" style={{ width: 110 }}>
        {label}
      </Text>
      <FlexLayout gap={1} align="center">
        {icon}
        {children}
      </FlexLayout>
    </FlexLayout>
  )
}

interface HomeProps {
  info: SessionInfo | null
  busy: boolean
  onStartLogin: (reset: boolean) => void
}

export default function Home({ info, busy, onStartLogin }: HomeProps) {
  const running = info?.login?.status === 'running'
  const loginDetail = info?.login?.detail

  let statusLine: ReactNode
  if (running) {
    statusLine = (
      <FlexLayout gap={1} align="center">
        <Spinner size="small" />
        <Text>{loginDetail || 'Waiting for manual login — complete it in the browser window.'}</Text>
      </FlexLayout>
    )
  } else if (info?.auth_snapshot_exists) {
    statusLine = (
      <FlexLayout gap={1} align="center">
        <StatusIndicator status="success" />
        <Text>Session saved — headless jobs can run without logging in again.</Text>
      </FlexLayout>
    )
  } else {
    statusLine = (
      <FlexLayout gap={1} align="center">
        <StatusIndicator status="error" />
        <Text>No saved session. Log in once so a session snapshot can be stored.</Text>
      </FlexLayout>
    )
  }

  const age = formatAge(info?.snapshot_age_seconds)

  return (
    <StackLayout gap={5}>
      <Card accent="left" elevation="raised">
        <CardHeader>
          <FlexLayout justify="space-between" align="center">
            <FlexLayout gap={1} align="center">
              <CookieSolidIcon size={2} />
              <Text styleAs="h4">Salesforce session</Text>
            </FlexLayout>
            <Text color="secondary" styleAs="label">
              {info?.auth_snapshot_exists ? 'authenticated' : 'not authenticated'}
            </Text>
          </FlexLayout>
        </CardHeader>
        <CardContent>
          <StackLayout gap={3}>
            {statusLine}

            <InfoRow label="Org">
              <Text styleAs="code">{info?.org ?? '—'}</Text>
            </InfoRow>
            <InfoRow icon={<UserSolidIcon size={1} />} label="Last login">
              <Text>{info?.last_login ?? 'never'}</Text>
            </InfoRow>
            <InfoRow icon={<ClockIcon size={1} />} label="Snapshot">
              <Text>
                {info?.auth_snapshot_exists
                  ? `saved ${age ?? ''} · ${info?.snapshot_cookie_count ?? '?'} cookies (${info?.snapshot_store ?? 'sqlite'})`
                  : 'none'}
              </Text>
            </InfoRow>

            <Divider />

            <FlexLayout gap={2} justify="space-between" align="center">
              <FlexLayout gap={2}>
                <Button
                  sentiment="accented"
                  appearance="solid"
                  disabled={busy}
                  onClick={() => onStartLogin(false)}
                >
                  {info?.auth_snapshot_exists ? 'Re-login' : 'Log in'}
                </Button>
                <Button
                  appearance="bordered"
                  disabled={busy}
                  onClick={() => onStartLogin(false)}
                >
                  <RefreshIcon aria-hidden /> Refresh snapshot
                </Button>
              </FlexLayout>
              {info?.auth_snapshot_exists && !running && (
                <Button
                  appearance="transparent"
                  disabled={busy}
                  onClick={() => onStartLogin(true)}
                >
                  Reset session
                </Button>
              )}
            </FlexLayout>
          </StackLayout>
        </CardContent>
      </Card>
    </StackLayout>
  )
}
