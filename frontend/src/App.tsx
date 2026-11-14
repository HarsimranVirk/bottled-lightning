/** App shell: Salt tabs for navigation, providers and the global health banner. */

import type { JSX } from 'react'
import { useState } from 'react'
import {
  FlexItem,
  FlexLayout,
  SaltProviderNext,
  Text,
} from '@salt-ds/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, NavLink, Outlet, Route, Routes } from 'react-router-dom'

import { AppFooter } from './components/AppFooter'
import { SettingsMenu } from './components/SettingsMenu'
import { SyncBanner } from './components/SyncBanner'
import { ThemeToggle } from './components/ThemeToggle'
import { DevDbPage } from './pages/DevDbPage'
import { DevStates } from './pages/DevStates'
import { DeviationsPage } from './pages/DeviationsPage'
import { HomePage } from './pages/HomePage'
import { JobsPage } from './pages/JobsPage'
import { Lms2ApprovalsPage } from './pages/Lms2ApprovalsPage'
import {
  useLogin,
  useRequestSync,
  useSaveSettings,
  useSession,
  useSettings,
  useSync,
  useVersion,
  useWorkflows,
} from './queries'
import { initialMode, nextMode, persistMode } from './theme'
import type { ThemeMode } from './theme'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
})

/** Fixed top-nav order; links never move when one is selected or overflowed. */
const NAV_ITEMS: { path: string; label: string; end?: boolean }[] = [
  { path: '/', label: 'Home', end: true },
  { path: '/deviations-z02', label: 'Deviations Z02' },
  { path: '/lms2-approvals', label: 'LMS2 Approvals' },
  { path: '/jobs', label: 'Jobs' },
]

interface ShellProps {
  mode: ThemeMode
  onToggleTheme: () => void
}

function Shell({ mode, onToggleTheme }: ShellProps): JSX.Element {
  const workflows = useWorkflows()
  const workflow = workflows.data?.[0]
  const session = useSession()
  const sync = useSync(workflow?.name ?? null)
  const version = useVersion()
  const login = useLogin()
  const refresh = useRequestSync(workflow?.name ?? null)
  const settings = useSettings()
  const saveSettings = useSaveSettings()

  return (
    <div className="shell">
      <header className="app-header">
        <FlexLayout justify="space-between" align="center" gap={2} wrap>
          <FlexLayout gap={3} align="center" wrap>
            <Text styleAs="h4">bottled-lightning</Text>
            <FlexItem grow={1}>
              <nav className="app-nav" aria-label="Main">
                {NAV_ITEMS.map((item) => (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    end={item.end}
                    className={({ isActive }) =>
                      `app-nav-link${isActive ? ' app-nav-link-active' : ''}`
                    }
                  >
                    {item.label}
                  </NavLink>
                ))}
              </nav>
            </FlexItem>
          </FlexLayout>
          <FlexLayout gap={2} align="center">
            <SettingsMenu
              settings={settings.data}
              saving={saveSettings.isPending}
              error={saveSettings.error?.message ?? null}
              onSave={(profile) => saveSettings.mutateAsync(profile)}
            />
            <ThemeToggle mode={mode} onToggle={onToggleTheme} />
          </FlexLayout>
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
  const [mode, setMode] = useState<ThemeMode>(initialMode)

  function toggleTheme(): void {
    const next = nextMode(mode)
    setMode(next)
    persistMode(next)
  }

  return (
    <SaltProviderNext mode={mode}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route element={<Shell mode={mode} onToggleTheme={toggleTheme} />}>
              <Route index element={<HomePage />} />
              <Route path="deviations-z02" element={<DeviationsPage />} />
              <Route path="deviations-z02/:key" element={<DeviationsPage />} />
              <Route path="lms2-approvals" element={<Lms2ApprovalsPage />} />
              <Route path="jobs" element={<JobsPage />} />
              <Route path="dev/states" element={<DevStates />} />
              <Route path="dev/db" element={<DevDbPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </SaltProviderNext>
  )
}
