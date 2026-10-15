import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend binds 127.0.0.1:5174 and is NOT exposed: the dev server proxies
// /api and /ws to it, so the browser only ever talks to one origin (5173).
// That also means the network URL (http://<lan-ip>:5173) works from a phone
// without a second port being reachable, and there is no cross-origin request
// to configure CORS for.
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:5174'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: Number(process.env.PORT) || 5173,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      // ws:true is what upgrades the live-state socket; without it the client
      // silently falls back to polling.
      '/ws': { target: API_TARGET, ws: true },
    },
  },
  // `vite preview` serves the production build — same proxy, so a built app
  // behaves identically to the dev one.
  preview: {
    port: Number(process.env.PORT) || 5173,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/ws': { target: API_TARGET, ws: true },
    },
  },
})
