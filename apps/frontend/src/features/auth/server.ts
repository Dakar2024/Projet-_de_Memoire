import { createServerFn } from '@tanstack/react-start'
import { deleteCookie, getCookie, setCookie } from '@tanstack/react-start/server'
import type { ApiErrorCode, User } from '@/shared/api/contracts'
import { USE_MOCKS, backendFetch, errorCode } from '@/shared/api/backend'
import {
  mockCompleteOnboarding,
  mockForgotPassword,
  mockResendVerification,
  mockResetPassword,
  mockSignIn,
  mockSignOut,
  mockSignUp,
  mockUserForToken,
  mockVerifyEmail,
} from '@/shared/mocks/auth-store'
import { emailSchema, onboardingSchema, resetPasswordSchema, signInSchema, signUpSchema, tokenSchema } from './schemas'

/**
 * Auth goes through server functions rather than browser calls: the route guard runs during SSR
 * too, and only the server can read the httpOnly session cookie on the incoming request.
 */

export type AuthResult = { ok: true } | { ok: false; code: ApiErrorCode }

export const MOCK_COOKIE = 'genomica_mock_session'

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
    if (USE_MOCKS) mockForgotPassword(data.email)
    else await backendFetch('/api/auth/forgot-password', { method: 'POST', json: data })
    return { ok: true }
  })

export const resendVerificationFn = createServerFn({ method: 'POST' })
  .inputValidator(emailSchema)
  .handler(async ({ data }): Promise<AuthResult> => {
    if (USE_MOCKS) {
      mockResendVerification(data.email)
      return { ok: true }
    }
    const response = await backendFetch('/api/auth/resend-verification', { method: 'POST', json: data })
    // Neutral, except a rate limit: the user should know to wait.
    return response.status === 429 ? { ok: false, code: 'rate_limited' } : { ok: true }
  })

/** Consumes the link from the verification e-mail; the account then signs in to complete its profile. */
export const verifyEmailFn = createServerFn({ method: 'POST' })
  .inputValidator(tokenSchema)
  .handler(async ({ data }): Promise<AuthResult> => {
    if (USE_MOCKS) {
      const result = mockVerifyEmail(data.token)
      return result.ok ? { ok: true } : result
    }
    const response = await backendFetch('/api/auth/verify-email', { method: 'POST', json: data })
    return response.ok ? { ok: true } : { ok: false, code: await errorCode(response) }
  })

export const resetPasswordFn = createServerFn({ method: 'POST' })
  .inputValidator(resetPasswordSchema)
  .handler(async ({ data }): Promise<AuthResult> => {
    if (USE_MOCKS) {
      const result = mockResetPassword(data.token, data.password)
      return result.ok ? { ok: true } : result
    }
    const response = await backendFetch('/api/auth/reset-password', { method: 'POST', json: data })
    return response.ok ? { ok: true } : { ok: false, code: await errorCode(response) }
  })

export type OnboardingResult = { ok: true; user: User } | { ok: false; code: ApiErrorCode }

/**
 * Profile completed after the e-mail check. The account becomes `pending_review` (the backend ends
 * the session) or, when the admin opened the domain, `active` straight away.
 */
export const completeOnboardingFn = createServerFn({ method: 'POST' })
  .inputValidator(onboardingSchema)
  .handler(async ({ data }): Promise<OnboardingResult> => {
    if (USE_MOCKS) {
      const result = mockCompleteOnboarding(getCookie(MOCK_COOKIE), data)
      if (!result.ok) return result
      if (result.value.status !== 'active') deleteCookie(MOCK_COOKIE, { path: '/' })
      return { ok: true, user: result.value }
    }
    const response = await backendFetch('/api/me/onboarding', { method: 'PUT', json: data })
    if (!response.ok) return { ok: false, code: await errorCode(response) }
    return { ok: true, user: (await response.json()) as User }
  })
