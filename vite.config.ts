import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { analyticsPlugin } from './server/analytics'
import { listingAiPlugin } from './server/listingAi'

export default defineConfig(({ mode }) => {
  // Unprefixed vars (the AI keys) are read here for the dev endpoint only and never reach the client bundle.
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), listingAiPlugin(env), analyticsPlugin()],
    server: { watch: { ignored: ['**/.data/**'] } },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            supabase: ['@supabase/supabase-js'],
          },
        },
      },
    },
  }
})
