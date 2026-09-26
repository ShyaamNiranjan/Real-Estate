import { createClient } from '@supabase/supabase-js'
import type { Database } from '../types/database'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

export const isSupabaseConfigured = Boolean(url && anonKey)

// A placeholder keeps module init from throwing so the app can render a setup screen instead.
export const supabase = createClient<Database>(
  url || 'http://localhost:54321',
  anonKey || 'missing-anon-key',
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      storageKey: 'yniidi-re-auth',
    },
  },
)

export const BUCKETS = {
  images: 'listing-images',
  videos: 'listing-videos',
  frames: 'listing-frames',
} as const
