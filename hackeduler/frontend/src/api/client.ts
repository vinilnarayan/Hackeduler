/**
 * Thin fetch wrapper. Session is an HttpOnly cookie (never readable by JS);
 * the CSRF token is echoed in X-CSRF-Token on every unsafe request.
 * The UI only renders what the backend returns: availability, end dates and
 * authorisation are all decided server-side.
 */
export class ApiError extends Error {
  status: number
  code: string
  details: any
  constructor(status: number, code: string, message: string, details?: any) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

let csrfToken: string | null = null
let onUnauthorized: (() => void) | null = null

export function setCsrfToken(t: string | null) {
  csrfToken = t
}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return m ? decodeURIComponent(m[1]) : null
}

export async function api<T = any>(method: string, url: string, body?: unknown, opts: { raw?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  const isForm = body instanceof FormData
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') headers['X-CSRF-Token'] = csrfToken ?? readCookie('hackeduler_csrf') ?? ''
  const res = await fetch(url, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  })
  if (opts.raw && res.ok) return res as unknown as T
  const text = await res.text()
  const data = text ? safeJson(text) : null
  if (!res.ok) {
    if (res.status === 401 && onUnauthorized && !url.endsWith('/auth/login')) onUnauthorized()
    const err = data?.error
    const msg =
      err?.message ??
      (Array.isArray(data?.detail) ? data.detail.map((d: any) => d.msg).join('; ') : `Request failed (${res.status})`)
    throw new ApiError(res.status, err?.code ?? 'error', msg, err?.details)
  }
  return data as T
}

function safeJson(t: string) {
  try {
    return JSON.parse(t)
  } catch {
    return { error: { message: t } }
  }
}

export const get = <T = any>(url: string) => api<T>('GET', url)
export const post = <T = any>(url: string, body?: unknown) => api<T>('POST', url, body ?? {})
export const patch = <T = any>(url: string, body?: unknown) => api<T>('PATCH', url, body ?? {})
export const put = <T = any>(url: string, body?: unknown) => api<T>('PUT', url, body ?? {})
export const del = <T = any>(url: string) => api<T>('DELETE', url)

export function qs(params: Record<string, string | number | boolean | null | undefined>) {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export function validationMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'validation_error' && Array.isArray(e.details) && e.details.length) {
      return e.details.map((d: any) => `${d.field ? d.field + ': ' : ''}${d.message}`).join('; ')
    }
    return e.message
  }
  return e instanceof Error ? e.message : String(e)
}
