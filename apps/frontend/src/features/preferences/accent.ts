import { createServerFn } from '@tanstack/react-start'
import { getCookie, setCookie } from '@tanstack/react-start/server'
import * as z from 'zod'

export const ACCENTS = ['helix', 'indigo', 'ocean', 'graphite'] as const
export type Accent = (typeof ACCENTS)[number]
export const DEFAULT_ACCENT: Accent = 'helix'

const ACCENT_COOKIE = 'accent'

function parseAccent(value: string | undefined): Accent {
  return ACCENTS.includes(value as Accent) ? (value as Accent) : DEFAULT_ACCENT
}

/** Read on the server so the first paint already has the right accent (no color flash). */
export const getAccentFn = createServerFn({ method: 'GET' }).handler(async () =>
  parseAccent(getCookie(ACCENT_COOKIE)),
)

export const setAccentFn = createServerFn({ method: 'POST' })
  .inputValidator(z.enum(ACCENTS))
  .handler(async ({ data }) => {
    setCookie(ACCENT_COOKIE, data, { path: '/', sameSite: 'lax', maxAge: 60 * 60 * 24 * 365 })
    return data
  })
