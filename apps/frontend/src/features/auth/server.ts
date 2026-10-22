import { createServerFn } from '@tanstack/react-start'
import { deleteCookie, getCookie, setCookie } from '@tanstack/react-start/server'
import type { ApiErrorCode, User } from '@/shared/api/contracts'
import { USE_MOCKS, backendFetch, errorCode } from '@/shared/api/backend'
import { mockSignIn, mockSignOut, mockSignUp, mockUserForToken } from '@/shared/mocks/auth-store'
import { emailSchema, signInSchema, signUpSchema } from './schemas'

/**
 * Auth goes through server functions rather than browser calls: the route guard runs during SSR
 * too, and only the server can read the httpOnly session cookie on the incoming request.
 */

export type AuthResult = { ok: true } | { ok: false; code: ApiErrorCode }

const MOCK_COOKIE = 'genomica_mock_session'

export const getSessionFn = createServerFn({ method: 'GET' }).handler(async (): Promise<User | null> => {
  if (USE_MOCKS) return mockUserForToken(getCookie(MOCK_COOKIE))
  const response = await backendFetch('/api/auth/me', { method: 'GET' })
  if (response.status === 401) return null
  if (!response.ok) throw new Error(`auth/me: ${response.status}`)
  return (await response.json()) as User
})

export const signInFn = createServerFn({ method: 'POST' })
  .inputValidator(signInSchema)
  .handler(async ({ data }): Promise<AuthResult> => {
    if (USE_MOCKS) {
      const result = mockSignIn(data)
      if (!result.ok) return result
      setCookie(MOCK_COOKIE, result.value.token, {
        httpOnly: true,
        sameSite: 'lax',
        path: '/',
        secure: import.meta.env.PROD,
        ...(data.remember ? { maxAge: 60 * 60 * 24 * 30 } : {}),
      })
      return { ok: true }
    }
    const response = await backendFetch('/api/auth/login', { method: 'POST', json: data })
    return response.ok ? { ok: true } : { ok: false, code: await errorCode(response) }
  })

export const signUpFn = createServerFn({ method: 'POST' })
  .inputValidator(signUpSchema)
  .handler(async ({ data }): Promise<AuthResult> => {
    if (USE_MOCKS) {
      const result = mockSignUp(data)
      return result.ok ? { ok: true } : result
    }
    const response = await backendFetch('/api/auth/register', { method: 'POST', json: data })
    return response.ok ? { ok: true } : { ok: false, code: await errorCode(response) }
  })

export const signOutFn = createServerFn({ method: 'POST' }).handler(async (): Promise<void> => {
  if (USE_MOCKS) {
    mockSignOut(getCookie(MOCK_COOKIE))
    deleteCookie(MOCK_COOKIE, { path: '/' })
    return
  }
  await backendFetch('/api/auth/logout', { method: 'DELETE' })
})

export const forgotPasswordFn = createServerFn({ method: 'POST' })
  .inputValidator(emailSchema)
  .handler(async ({ data }): Promise<AuthResult> => {
    // Neutral answer in both modes: never reveal whether an account exists.
    if (!USE_MOCKS) await backendFetch('/api/auth/forgot-password', { method: 'POST', json: data })
    return { ok: true }
  })
