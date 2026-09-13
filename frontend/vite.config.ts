import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Proxy API calls to the local FastAPI server (see ../backend) so the
    // dev UI can call same-origin `/api/...` paths — no CORS involved for
    // the normal dev flow. The API also allows this dev server's own
    // origin directly (see backend/app/api.py) for anyone hitting it
    // straight from the browser or a separate tool.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
