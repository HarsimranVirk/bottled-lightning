import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // dev: forward API calls to the FastAPI backend
      '/api': 'http://localhost:8765',
    },
  },
})
