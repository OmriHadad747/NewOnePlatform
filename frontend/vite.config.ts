import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The frontend talks to the FastAPI backend exactly like the CLI does, over
// HTTP. In dev we proxy /api -> the backend so there are no CORS concerns and
// the same-origin path keeps working in production behind a reverse proxy.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.AIPM_BACKEND_URL || 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})
