const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')
const API_PREFIX = '/api/v1'

export class ApiError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export function getAccessToken(): string | null {
  return localStorage.getItem('trustlayerAccessToken')
}

export function setAccessToken(token: string | null) {
  if (token) localStorage.setItem('trustlayerAccessToken', token)
  else localStorage.removeItem('trustlayerAccessToken')
}

function authHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra)
  const token = getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return headers
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const message = typeof payload?.detail === 'string'
      ? payload.detail
      : payload?.error?.message || payload?.message || `Request failed (${response.status})`
    throw new ApiError(message, response.status, payload?.error?.code)
  }
  return payload as T
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = authHeaders(options.headers)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${API_PREFIX}${path.startsWith('/') ? path : `/${path}`}`, {
      ...options,
      headers,
    })
  } catch {
    throw new ApiError(`Cannot reach TRUSTLAYER backend at ${API_BASE_URL}. Start the FastAPI server and check VITE_API_BASE_URL.`, 0)
  }
  return parseResponse<T>(response)
}

export async function apiUpload<T>(path: string, form: FormData, idempotencyKey?: string): Promise<T> {
  const headers = authHeaders()
  if (idempotencyKey) headers.set('Idempotency-Key', idempotencyKey)
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, { method: 'POST', body: form, headers })
  } catch {
    throw new ApiError(`Cannot reach TRUSTLAYER backend at ${API_BASE_URL}.`, 0)
  }
  return parseResponse<T>(response)
}

export function getWebSocketUrl(path: string): string {
  const url = new URL(`${API_PREFIX}${path}`, API_BASE_URL)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

export { API_BASE_URL, API_PREFIX }
