import { useCallback, useEffect, useState } from 'react'
import {
  SaltProviderNext,
  Button,
  StackLayout,
  FlexLayout,
  Text,
  StatusIndicator,
} from '@salt-ds/core'
import Home from './pages/Home'
import DeviationsZ02 from './pages/DeviationsZ02'
import Deck from './pages/Deck'
import History from './pages/History'
import { api, errorMessage } from './api'
import { loadStored, saveStored } from './shared'
import type { Route, SessionInfo } from './types'

const ROUTES: readonly Route[] = ['home', 'deviations-z02']

function readRoute(): Route {
  const raw = window.location.hash.replace(/^#\/?/, '')
  return ROUTES.includes(raw as Route) ? (raw as Route) : 'home'
}

function useHashRoute(): [Route, (route: Route) => void] {
  const [route, setRoute] = useState<Route>(readRoute)
  useEffect(() => {
    const onChange = (): void => setRoute(readRoute())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  const navigate = (next: Route): void => { window.location.hash = `/${next}` }
  return [route, navigate]
}

interface NavItem {
  id: Route
  label: string
  group?: string
}

const NAV: readonly NavItem[] = [
  { id: 'home', label: 'Home' },
  { id: 'deviations-z02', label: 'Deviations Z02' },
]

function App() {
  const [route, navigate] = useHashRoute()
  const [info, setInfo] = useState<SessionInfo | null>(() => loadStored())
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState<string | null>(null)
  const [navOpen, setNavOpen] = useState(false)
  const [z2Tab, setZ2Tab] = useState<'deck' | 'history' | 'extraction'>('deck')
  const busy = info?.login?.status === 'running'

  const refresh = useCallback(async (): Promise<void> => {
    try {
      const data = await api.sessionStatus()
      setInfo(data)
      saveStored(data)
      setError(null)
    } catch (e) {
      setError(`Backend unreachable: ${errorMessage(e)}`)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = setInterval(refresh, busy ? 2000 : 5000)
    return () => clearInterval(id)
  }, [busy, refresh])

  useEffect(() => {
    void api.updateStatus().then((data) => setVersion(data.app_version)).catch(() => undefined)
  }, [])

  const startLogin = async (reset: boolean): Promise<void> => {
    try {
      await api.startLogin(reset)
      void refresh()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const go = (r: Route): void => {
    navigate(r)
    setNavOpen(false)
  }

  return (
    <SaltProviderNext
      mode="light"
      density="high"
      accent="blue"
      corner="sharp"
      headingFont="Open Sans"
      actionFont="Open Sans"
    >
      <StackLayout gap={4} className="app-shell">
        <header className="app-header">
          <FlexLayout justify="space-between" align="center" gap={2}>
            <StackLayout gap={0.5} style={{ minWidth: 0 }}>
              <Text color="secondary" styleAs="label" className="app-subtitle">
                Salesforce Lightning Automation · local network service
              </Text>
              <Text styleAs="h3" onClick={() => go('home')} style={{ cursor: 'pointer', margin: 0 }}>
                bottled-lightning
              </Text>
            </StackLayout>

            {/* Desktop nav */}
            <nav className="app-nav app-nav--desktop" aria-label="Primary">
              {NAV.map((n) => (
                <Button
                  key={n.id}
                  appearance="transparent"
                  sentiment={route === n.id ? 'accented' : 'neutral'}
                  onClick={() => go(n.id)}
                >
                  {n.label}
                </Button>
              ))}
            </nav>

            {/* Mobile nav toggle */}
            <Button
              className="app-nav-toggle"
              appearance="bordered"
              onClick={() => setNavOpen((v) => !v)}
              aria-expanded={navOpen}
              aria-label="Toggle navigation"
            >
              {navOpen ? '✕' : '☰'}
            </Button>
          </FlexLayout>

          {/* Mobile nav panel */}
          {navOpen && (
            <nav className="app-nav app-nav--mobile" aria-label="Primary mobile">
              {NAV.map((n) => (
                <Button
                  key={n.id}
                  appearance="transparent"
                  sentiment={route === n.id ? 'accented' : 'neutral'}
                  onClick={() => go(n.id)}
                  style={{ width: '100%', justifyContent: 'flex-start' }}
                >
                  {n.label}
                </Button>
              ))}
            </nav>
          )}
        </header>

        {error && (
          <FlexLayout gap={1} align="center">
            <StatusIndicator status="error" />
            <Text color="error">{error}</Text>
          </FlexLayout>
        )}

        {route === 'deviations-z02' ? (
          <StackLayout gap={3}>
            <FlexLayout gap={2} className="sub-nav">
              <Button
                appearance="transparent"
                sentiment={z2Tab === 'deck' ? 'accented' : 'neutral'}
                onClick={() => setZ2Tab('deck')}
              >
                Deck
              </Button>
              <Button
                appearance="transparent"
                sentiment={z2Tab === 'history' ? 'accented' : 'neutral'}
                onClick={() => setZ2Tab('history')}
              >
                History
              </Button>
              <Button
                appearance="transparent"
                sentiment={z2Tab === 'extraction' ? 'accented' : 'neutral'}
                onClick={() => setZ2Tab('extraction')}
              >
                Extraction
              </Button>
            </FlexLayout>
            {z2Tab === 'history' ? <History /> : z2Tab === 'extraction' ? <DeviationsZ02 /> : <Deck />}
          </StackLayout>
        ) : (
          <Home info={info} busy={busy} onStartLogin={startLogin} />
        )}

        <Text color="secondary" styleAs="code" style={{ fontSize: 11 }}>
          last checked: {info?.checked_at ? new Date(info.checked_at).toLocaleString() : '—'} (mirrored to localStorage)
        </Text>

      </StackLayout>
      <footer
        className="app-footer"
      >
        <Text color="secondary" styleAs="code" style={{ fontSize: 11 }}>
          bottled-lightning {version ? `v${version}` : '…'}
        </Text>
      </footer>
    </SaltProviderNext>
  )
}

export default App