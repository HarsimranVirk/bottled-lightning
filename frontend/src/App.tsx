/** App shell: providers, navigation and the global health banner. */

import type { JSX } from 'react'
import { SaltProviderNext, FlexLayout, Text } from '@salt-ds/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Link, Outlet, Route, Routes } from 'react-router-dom'

import { QueueBar } from './components/QueueBar'
import { SyncBanner } from './components/SyncBanner'
import { DevStates } from './pages/DevStates'
import { HomePage } from './pages/HomePage'
import { JobsPage } from './pages/JobsPage'
import { DeviationsPage } from './pages/DeviationsPage'
import { useLogin, useRequestSync, useSession, useSync, useWorkers, useWorkflows } from './queries'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
})

function Shell(): JSX.Element {
  const workflows = useWorkflows()
  const workflow = workflows.data?.[0]
  const session = useSession()
  const sync = useSync(workflow?.name ?? null)
  const workers = useWorkers()
  const login = useLogin()
  const refresh = useRequestSync(workflow?.name ?? null)

  return (
    <div className="shell">
      <header className="topbar">
        <strong>bottled-lightning</strong>
        <nav>
          <Link to="/">Home</Link>
          <Link to="/deviations-z02">Deviations Z02</Link>
          <Link to="/jobs">Jobs</Link>
        </nav>
        <QueueBar queue={workers.data} />
      </header>
      <main className="content">
        <FlexLayout direction="column" gap={3}>
          <SyncBanner
            session={session.data}
            sync={sync.data}
            onLogin={() => login.mutate()}
            onRefresh={() => refresh.mutate()}
            refreshing={refresh.isPending}
          />
          <Outlet />
          <Text color="secondary" className="footer">
            Local tool · Salesforce UI automation
          </Text>
        </FlexLayout>
      </main>
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
