#!/usr/bin/env node
// Creates (or promotes) the first admin user using the Supabase service role key.
// Usage: node scripts/bootstrap-admin.mjs admin@example.com
// Reads VITE_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from .env.local or the environment.
// A generated password is appended to .env.local as ADMIN_BOOTSTRAP_PASSWORD (never printed, never committed).

import { appendFileSync, existsSync, readFileSync } from 'node:fs'
import { randomBytes } from 'node:crypto'

const envFile = new URL('../.env.local', import.meta.url)
const fileEnv = existsSync(envFile)
  ? Object.fromEntries(
      readFileSync(envFile, 'utf8')
        .split(/\r?\n/)
        .map((l) => l.match(/^([A-Z0-9_]+)=(.*)$/))
        .filter(Boolean)
        .map((m) => [m[1], m[2].trim()]),
    )
  : {}
const env = { ...fileEnv, ...process.env }

const url = env.VITE_SUPABASE_URL
const key = env.SUPABASE_SERVICE_ROLE_KEY
const email = process.argv[2] || env.ADMIN_BOOTSTRAP_EMAIL
if (!url || !key || !email) {
  console.error('Need VITE_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and an email argument.')
  process.exit(1)
}

const headers = { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' }
const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
const password = Array.from(randomBytes(22), (b) => alphabet[b % alphabet.length]).join('') + '-9a'

async function findUser() {
  const res = await fetch(`${url}/auth/v1/admin/users?per_page=1000`, { headers })
  const body = await res.json()
  return (body.users ?? []).find((u) => u.email?.toLowerCase() === email.toLowerCase())
}

let user = await findUser()
if (!user) {
  const res = await fetch(`${url}/auth/v1/admin/users`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ email, password, email_confirm: true }),
  })
  if (!res.ok) {
    console.error('Create user failed:', res.status, await res.text())
    process.exit(1)
  }
  user = await res.json()
  appendFileSync(envFile, `\nADMIN_BOOTSTRAP_EMAIL=${email}\nADMIN_BOOTSTRAP_PASSWORD=${password}\n`)
  console.log(`Created ${email}. Password written to .env.local (ADMIN_BOOTSTRAP_PASSWORD).`)
} else {
  console.log(`${email} already exists; promoting to admin.`)
}

const promote = await fetch(`${url}/rest/v1/profiles?on_conflict=id`, {
  method: 'POST',
  headers: { ...headers, Prefer: 'resolution=merge-duplicates' },
  body: JSON.stringify({ id: user.id, email, role: 'admin' }),
})
if (!promote.ok) {
  console.error('Promote failed:', promote.status, await promote.text())
  process.exit(1)
}
console.log('Admin role granted.')
