/** App shell: Salt tabs for navigation, providers and the global health banner. */

import type { JSX } from 'react'
import {
  FlexItem,
  FlexLayout,
  SaltProviderNext,
  Tab,
  TabBar,
  TabList,
  TabTrigger,
  Tabs,
  Text,
} from '@salt-ds/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { AppFooter } from './components/AppFooter'
import { QueueBar } from './components/QueueBar'
import { SyncBanner } from './components/SyncBanner'
import { DevStates } from './pages/DevStates'
import { DeviationsPage } from './pages/DeviationsPage'
import { HomePage } from './pages/HomePage'
import { JobsPage } from './pages/JobsPage'
import {
  useLogin,
  useRequestSync,
  useSession,
  useSync,
  useVersion,
  useWorkers,
  useWorkflows,
} from './queries'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
})

const TAB_PATHS: Record<string, string> = {
  home: '/',
  deviations: '/deviations-z02',
  jobs: '/jobs',
}

function tabFor(pathname: string): string {
  if (pathname.startsWith('/jobs')) return 'jobs'
  if (pathname.startsWith('/deviations-z02')) return 'deviations'
  return 'home'
}

function Shell(): JSX.Element {
  const navigate = useNavigate()
  const location = useLocation()
  const workflows = useWorkflows()
  const workflow = workflows.data?.[0]
  const session = useSession()
  const sync = useSync(workflow?.name ?? null)
  const version = useVersion()
  const workers = useWorkers()
  const login = useLogin()
  const refresh = useRequestSync(workflow?.name ?? null)

  return (
    <div className="shell">
      <header className="app-header">
        <FlexLayout justify="space-between" align="center" gap={2} wrap>
          <FlexLayout gap={3} align="center" wrap>
            <Text styleAs="h4">bottled-lightning</Text>
            <FlexItem grow={1}>
            <Tabs
              className="app-tabs"
              value={tabFor(location.pathname)}
              onChange={(_event, value) => navigate(TAB_PATHS[value] ?? '/')}
            >
              <TabBar>
                <TabList>
                  <Tab value="home">
                    <TabTrigger>Home</TabTrigger>
                  </Tab>
                  <Tab value="deviations">
                    <TabTrigger>Deviations Z02</TabTrigger>
                  </Tab>
                  <Tab value="jobs">
                    <TabTrigger>Jobs</TabTrigger>
                  </Tab>
                </TabList>
              </TabBar>
            </Tabs>
            </FlexItem>
          </FlexLayout>
          <QueueBar queue={workers.data} />
        </FlexLayout>
      </header>

      <main className="content">
        <FlexLayout direction="column" gap={2}>
          <SyncBanner
            session={session.data}
            sync={sync.data}
            onLogin={() => login.mutate()}
            onRefresh={() => refresh.mutate()}
            refreshing={refresh.isPending}
          />
          <Outlet />
        </FlexLayout>
      </main>

      <AppFooter
        version={version.data?.version}
        session={session.data}
        sync={sync.data}
        onRefresh={() => refresh.mutate()}
        refreshing={refresh.isPending}
      />
    </div>
  )
}

export default function App(): JSX.Element {
  return (
    <SaltProviderNext>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route element={<Shell />}>
              <Route index element={<HomePage />} />
              <Route path="deviations-z02" element={<DeviationsPage />} />
              <Route path="deviations-z02/:key" element={<DeviationsPage />} />
              <Route path="jobs" element={<JobsPage />} />
              <Route path="dev/states" element={<DevStates />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </SaltProviderNext>
  )
}
