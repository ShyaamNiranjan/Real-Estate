import type { components } from './schema'

type ErrorBody = components['schemas']['ErrorBody']

const NETWORK_MESSAGE = "We couldn't reach Scrollwalk. Check your connection and try again."
const UNKNOWN_MESSAGE = 'Something went wrong on our side. Please try again in a moment.'

/** Every API failure, normalised from `{ error: { code, message, fields } }`. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fields: Record<string, string>

  constructor(status: number, code: string, message: string, fields?: Record<string, string> | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fields = fields ?? {}
  }
}

function isErrorEnvelope(value: unknown): value is { error: ErrorBody } {
  if (!value || typeof value !== 'object' || !('error' in value)) return false
  const body = (value as { error: unknown }).error
  return !!body && typeof body === 'object' && 'code' in body && 'message' in body
}

export function toApiError(status: number, payload: unknown): ApiError {
  if (isErrorEnvelope(payload)) {
    const { code, message, fields } = payload.error
    return new ApiError(status, code, message, fields)
  }
  return new ApiError(status, status >= 500 || status === 0 ? 'server_error' : 'unknown_error', UNKNOWN_MESSAGE)
}

export function asApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err
  return new ApiError(0, 'network_error', NETWORK_MESSAGE)
}

type Result<T> = { data?: T; error?: unknown; response: Response }

/** Resolves to the response data, or throws an `ApiError` for any non-2xx answer or network failure. */
export async function unwrap<T>(request: Promise<Result<T>>): Promise<T> {
  let result: Result<T>
  try {
    result = await request
  } catch {
    throw new ApiError(0, 'network_error', NETWORK_MESSAGE)
  }
  if (!result.response.ok) throw toApiError(result.response.status, result.error)
  return result.data as T
}
