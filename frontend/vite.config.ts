import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 後端跑 :8000;如果用同 origin 開發,可以加 proxy 避免 CORS:
    proxy: {
      '/auth': 'http://localhost:8000',
      '/sessions': 'http://localhost:8000',
      '/me': 'http://localhost:8000',
      '/uploads': 'http://localhost:8000',
      '/models': 'http://localhost:8000',
      '/healthz': 'http://localhost:8000',
      '/chat': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
