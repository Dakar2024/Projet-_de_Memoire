import { getRequestHeader, getRequestIP, setResponseHeader } from '@tanstack/react-start/server'
import type { ApiErrorCode } from './contracts'
import { isApiErrorCode } from './errors'

/**
 * Server-side access to the Litestar backend, for server functions only (SSR loaders, route guards).
 * The browser's session cookie is forwarded as is and any Set-Cookie is relayed back, so the
 * frontend server never reads or stores the session token itself.
 */

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

/** Frozen gold figures for /api/panels until the backend's analytics step serves them. */
export const USE_PANELS_FIXTURE = USE_MOCKS || import.meta.env.VITE_PANELS_FIXTURE === 'true'

function backendUrl(path: string): URL {
  const base = process.env.API_INTERNAL_URL
  if (!base) throw new Error('API_INTERNAL_URL manquant : URL interne du backend (voir .env.example)')
  return new URL(path, base)
}

export async function backendFetch(
  path: string,
  init: { method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'; json?: unknown },
) {
  // Every call reaches the backend from this server: without the browser's address, all users would
  // share one rate limit. The backend reads only the last entry, the one written here.
  const clientIp = getRequestIP()
  const response = await fetch(backendUrl(path), {
    method: init.method,
    headers: {
      accept: 'application/json',
      ...(init.json === undefined ? {} : { 'content-type': 'application/json' }),
      cookie: getRequestHeader('cookie') ?? '',
      ...(clientIp ? { 'x-forwarded-for': clientIp } : {}),
    },
    body: init.json === undefined ? undefined : JSON.stringify(init.json),
  })
  const setCookies = response.headers.getSetCookie()
  if (setCookies.length > 0) setResponseHeader('set-cookie', setCookies)
  return response
}

/** Public error code of a failed backend answer; anything unexpected becomes `internal`. */
export async function errorCode(response: Response): Promise<ApiErrorCode> {
  try {
    const body = (await response.json()) as { error?: unknown }
    return isApiErrorCode(body.error) ? body.error : 'internal'
  } catch {
    return response.status >= 500 ? 'unavailable' : 'internal'
  }
}
