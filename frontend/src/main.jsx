import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// Salt DS required fonts (Open Sans weights + PT Mono)
import '@fontsource/open-sans/300.css'
import '@fontsource/open-sans/400.css'
import '@fontsource/open-sans/500.css'
import '@fontsource/open-sans/600.css'
import '@fontsource/open-sans/700.css'
import '@fontsource/pt-mono/400.css'

// Salt DS theme: baseline reset (opt-in) + base theme + J.P. Morgan "next" layer
import '@salt-ds/theme/css/baseline.css'
import '@salt-ds/theme/index.css'
import '@salt-ds/theme/css/theme-next.css'

import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
