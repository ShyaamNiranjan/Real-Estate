import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { AuthProvider } from './lib/auth'
import { SiteProvider } from './lib/site'
import { isSupabaseConfigured } from './lib/supabase'
import { router } from './router'
import { SetupRequired } from './components/SetupRequired'
import './index.css'
import './styles/public.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {isSupabaseConfigured ? (
      <SiteProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </SiteProvider>
    ) : (
      <SetupRequired />
    )}
  </StrictMode>,
)
