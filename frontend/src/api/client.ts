const API_BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

const TOKEN_KEY = 'ambifo_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Options = { method?: string; body?: unknown }

export async function api<T>(
  path: string,
  { method = 'GET', body }: Options = {},
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  const token = getToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  const resp = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (resp.status === 204) {
    return undefined as T
  }
  if (resp.status === 401) {
    setToken(null)
  }
  const data = await resp.json().catch(() => null)
  if (!resp.ok) {
    const detail = data?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg).join(', ')
          : `Request failed (${resp.status})`
    throw new ApiError(resp.status, message)
  }
  return data as T
}