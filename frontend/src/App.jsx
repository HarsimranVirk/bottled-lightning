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
import { api } from './api'
import { loadStored, saveStored } from './shared'

function useHashRoute() {
  const read = () => (window.location.hash.replace(/^#\/?/, '') || 'home')
  const [route, setRoute] = useState(read)
  useEffect(() => {
    const onChange = () => setRoute(read())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  const navigate = (r) => { window.location.hash = `/${r}` }
  return [route, navigate]
}

const NAV = [
  { id: 'home', label: 'Home' },
  { id: 'deviations-z02', label: 'Deviations Z02' },
]

function App() {
  const [route, navigate] = useHashRoute()
  const [info, setInfo] = useState(() => loadStored())
  const [error, setError] = useState(null)
  const busy = info?.login?.status === 'running'

  const refresh = useCallback(async () => {
    try {
      const data = await api.sessionStatus()
      setInfo(data)
      saveStored(data)
      setError(null)
    } catch (e) {
      // keep showing last known session info from localStorage
      setError(`Backend unreachable: ${e.message}`)
    }
  }, [])

  useEffect(() => {
    void refresh() // initial load; async so state updates after await
    const id = setInterval(refresh, busy ? 2000 : 5000)
    return () => clearInterval(id)
  }, [busy, refresh])

  const startLogin = async (reset) => {
    try {
      await api.startLogin(reset)
      refresh()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <SaltProviderNext
      mode="light"
      density="high" // most compact Salt density
      accent="blue"
      corner="sharp"
      headingFont="Open Sans"
      actionFont="Open Sans"
    >
      <StackLayout gap={4} style={{ maxWidth: 760, margin: '0 auto', padding: '24px 28px 48px' }}>
        <FlexLayout justify="space-between" align="center">
          <StackLayout gap={0.5}>
            <Text color="secondary" styleAs="label">
              Salesforce Lightning extractor · local network service
            </Text>
            <Text styleAs="h3" onClick={() => navigate('home')} style={{ cursor: 'pointer' }}>
              bottled-lightning
            </Text>
          </StackLayout>
          <FlexLayout gap={1} align="center">
            {NAV.map((n) => (
              <Button
                key={n.id}
                appearance="transparent"
                sentiment={route === n.id ? 'accented' : 'neutral'}
                onClick={() => navigate(n.id)}
              >
                {n.label}
              </Button>
            ))}
          </FlexLayout>
        </FlexLayout>

        {error && (
          <FlexLayout gap={1} align="center">
            <StatusIndicator status="error" />
            <Text status="error">{error}</Text>
          </FlexLayout>
        )}

        {route === 'deviations-z02' || route === 'deck' ? (
          <Deck />
        ) : route === 'runs' ? (
          <DeviationsZ02 />
        ) : (
          <Home info={info} busy={busy} onStartLogin={startLogin} />
        )}

        <Text color="secondary" styleAs="code" style={{ fontSize: 11 }}>
          last checked: {info?.checked_at ? new Date(info.checked_at).toLocaleString() : '—'} (mirrored to localStorage)
        </Text>
      </StackLayout>
    </SaltProviderNext>
  )
}

export default App
