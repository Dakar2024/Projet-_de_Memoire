const PROBE_ORIGIN = 'https://genomica.invalid'

/**
 * Where to go after signing in. Only a same-origin path inside the signed-in area is accepted:
 * anything else (absolute URL, protocol-relative `//host`, backslashes, control characters,
 * auth pages) falls back to the default, so a crafted link cannot send the user to another site.
 */
export function safeRedirect(target: unknown, fallback: string): string {
  if (typeof target !== 'string' || !target.startsWith('/') || target.startsWith('//')) return fallback
  if (/[\\\u0000-\u001f\u007f]/.test(target)) return fallback
  let url: URL
  try {
    url = new URL(target, PROBE_ORIGIN)
  } catch {
    return fallback
  }
  if (url.origin !== PROBE_ORIGIN) return fallback
  // Never bounce back to an auth page (would loop once signed in).
  if (/^\/[a-z]{2}\/(sign-in|sign-up|pending|forgot-password)(\/|$)/.test(url.pathname)) return fallback
  return url.pathname + url.search + url.hash
}
