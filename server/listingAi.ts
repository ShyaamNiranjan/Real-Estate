import { readFileSync } from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { fileURLToPath } from 'node:url'
import type { Plugin } from 'vite'
import { LISTING_COPY_SCHEMA, MAX_SUMMARY_CHARS, TONES, type GenerateRequest } from '../src/lib/listingCopy'

/**
 * Prototype of the listing-writer endpoint (moves to FastAPI in the real build). Runs inside the Vite
 * dev server so the API key stays server-side. Any OpenAI-compatible provider works: Gemini for
 * development, GPT-6 Luna in production, switched by env only.
 */

const PROMPT_FILE = fileURLToPath(new URL('./prompts/listing-content.v1.md', import.meta.url))
const DAILY_LIMIT = 10
const TIMEOUT_MS = 90_000
/** A model that hasn't answered by then is skipped for the next one. */
const FIRST_BYTE_MS = 25_000

type Env = { AI_BASE_URL?: string; AI_API_KEY?: string; AI_MODEL?: string; GEMINI_API_KEY?: string; GEMINI_MODEL?: string }

/** Free-tier models are often busy (503/429), so the next one is tried before giving up. */
const GEMINI_FALLBACKS = ['gemini-3.8-flash', 'gemini-3.5-flash', 'gemini-flash-latest', 'gemini-flash-lite-latest']

function provider(env: Env) {
  if (env.AI_API_KEY) {
    return { baseUrl: env.AI_BASE_URL || 'https://api.openai.com/v1', key: env.AI_API_KEY, models: [env.AI_MODEL || 'gpt-6-luna'] }
  }
  if (env.GEMINI_API_KEY) {
    const models = [...new Set([env.GEMINI_MODEL, ...GEMINI_FALLBACKS].filter((m): m is string => Boolean(m)))]
    return { baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai', key: env.GEMINI_API_KEY, models }
  }
  return null
}

const usage = new Map<string, number>()

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = ''
    req.on('data', (c) => {
      data += c
      if (data.length > 64_000) reject(new Error('Request too large'))
    })
    req.on('end', () => resolve(data))
    req.on('error', reject)
  })
}

function fail(res: ServerResponse, status: number, message: string) {
  res.statusCode = status
  res.setHeader('content-type', 'application/json')
  res.end(JSON.stringify({ error: message }))
}

function validate(body: unknown): GenerateRequest | string {
  const b = body as Partial<GenerateRequest> | null
  if (!b || typeof b !== 'object') return 'Invalid request'
  if (typeof b.listingId !== 'string' || !b.listingId) return 'Missing listing'
  if (typeof b.summary !== 'string' || b.summary.trim().length < 20) return 'Add a summary of the home first'
  if (b.summary.length > MAX_SUMMARY_CHARS) return 'Summary is too long'
  if (!b.facts || typeof b.facts.title !== 'string') return 'Missing listing details'
  const tone = TONES.some((t) => t.key === b.tone) ? b.tone! : 'luxury'
  const f = b.facts
  const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
  const text = (v: unknown, max: number) => (typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : null)
  return {
    listingId: b.listingId,
    summary: b.summary.trim(),
    tone,
    country: typeof b.country === 'string' ? b.country.slice(0, 8) : 'US',
    facts: {
      title: f.title.slice(0, 120),
      location: text(f.location, 160),
      price: text(f.price, 60),
      bedrooms: num(f.bedrooms),
      bathrooms: num(f.bathrooms),
      areaSqft: num(f.areaSqft),
      experience: f.experience === 'photography' ? 'photography' : 'immersive walkthrough',
    },
  }
}

async function generate(req: IncomingMessage, res: ServerResponse, env: Env) {
  const p = provider(env)
  if (!p) return fail(res, 503, 'No AI key configured')

  let input: GenerateRequest
  try {
    const parsed = validate(JSON.parse(await readBody(req)))
    if (typeof parsed === 'string') return fail(res, 400, parsed)
    input = parsed
  } catch {
    return fail(res, 400, 'Invalid request')
  }

  const day = `${input.listingId}:${new Date().toISOString().slice(0, 10)}`
  const used = usage.get(day) ?? 0
  if (used >= DAILY_LIMIT) return fail(res, 429, `You can generate this listing ${DAILY_LIMIT} times a day. Edit the sections directly, or try again tomorrow.`)

  const system = readFileSync(PROMPT_FILE, 'utf8')
  const user = JSON.stringify({ facts: input.facts, summary: input.summary, tone: input.tone, country: input.country })
  const abort = new AbortController()
  const timer = setTimeout(() => abort.abort(), TIMEOUT_MS)
  req.on('close', () => {
    if (!res.writableEnded) abort.abort()
  })

  let lastError = 'The writer is unavailable'
  try {
    for (const model of p.models) {
      for (const format of ['json_schema', 'json_object'] as const) {
        if (abort.signal.aborted) break
        const attempt = new AbortController()
        const stalled = setTimeout(() => attempt.abort(), FIRST_BYTE_MS)
        const onAbort = () => attempt.abort()
        abort.signal.addEventListener('abort', onAbort, { once: true })
        const upstream = await fetch(`${p.baseUrl}/chat/completions`, {
          method: 'POST',
          signal: attempt.signal,
          headers: { 'content-type': 'application/json', authorization: `Bearer ${p.key}` },
          body: JSON.stringify({
            model,
            stream: true,
            temperature: 0.7,
            messages: [
              { role: 'system', content: format === 'json_object' ? `${system}\n\nJSON schema:\n${JSON.stringify(LISTING_COPY_SCHEMA)}` : system },
              { role: 'user', content: user },
            ],
            response_format:
              format === 'json_schema'
                ? { type: 'json_schema', json_schema: { name: 'listing_copy', strict: true, schema: LISTING_COPY_SCHEMA } }
                : { type: 'json_object' },
          }),
        })
          .catch((err: Error) => {
            lastError = err.name === 'AbortError' ? 'The writer took too long' : err.message
            console.warn(`[listing-ai] ${model} (${format}) → ${lastError}`)
            return null
          })
          .finally(() => clearTimeout(stalled))
        if (!upstream) break
        if (!upstream.ok || !upstream.body) {
          const detail = await upstream.text().catch(() => '')
          lastError = `${model}: ${upstream.status}`
          console.warn(`[listing-ai] ${model} (${format}) → ${upstream.status} ${detail.slice(0, 200)}`)
          if (upstream.status === 400 && format === 'json_schema') continue
          break
        }

        usage.set(day, used + 1)
        res.statusCode = 200
        res.setHeader('content-type', 'text/plain; charset=utf-8')
        res.setHeader('cache-control', 'no-store')
        res.setHeader('x-ye-model', model)
        res.setHeader('x-ye-remaining', String(DAILY_LIMIT - used - 1))

        const reader = upstream.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''
          for (const line of lines) {
            const data = line.startsWith('data:') ? line.slice(5).trim() : ''
            if (!data || data === '[DONE]') continue
            try {
              const delta = JSON.parse(data).choices?.[0]?.delta?.content
              if (delta) res.write(delta)
            } catch {
              /* keep-alive or partial line */
            }
          }
        }
        res.end()
        return
      }
    }
    fail(res, 502, lastError)
  } finally {
    clearTimeout(timer)
  }
}

export function listingAiPlugin(env: Env): Plugin {
  return {
    name: 'ye-listing-ai',
    configureServer(server) {
      server.middlewares.use('/api/listing-content', (req, res, next) => {
        if (req.method !== 'POST') return next()
        generate(req, res, env).catch((err: Error) => {
          console.error('[listing-ai]', err)
          if (!res.headersSent) fail(res, 500, 'Generation failed')
          else res.end()
        })
      })
    },
  }
}
