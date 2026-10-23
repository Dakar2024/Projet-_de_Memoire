import { describe, expect, it } from 'vitest'
import { afterEach, vi } from 'vitest'
import {
  mockAccessRequests,
  mockCompleteOnboarding,
  mockDecide,
  mockForgotPassword,
  mockResetPassword,
  mockSignIn,
  mockSignOut,
  mockSignUp,
  mockUserForToken,
  mockVerifyEmail,
} from './auth-store'

const request = {
  password: 'Abcdefghijk1!',
  noPatientDataPledge: true as const,
  termsAccepted: true as const,
}

describe('mock auth store', () => {
  it('opens and closes a session for an active account', () => {
    const result = mockSignIn({ email: 'DEMO@genomica.local ', password: 'genomica-demo-2026', remember: false })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(mockUserForToken(result.value.token)?.email).toBe('demo@genomica.local')
    mockSignOut(result.value.token)
    expect(mockUserForToken(result.value.token)).toBeNull()
  })

  it('does not tell a wrong password from an unknown address', () => {
    expect(mockSignIn({ email: 'demo@genomica.local', password: 'nope', remember: false })).toEqual({
      ok: false,
      code: 'invalid_credentials',
    })
    expect(mockSignIn({ email: 'nobody@x.org', password: 'nope', remember: false })).toEqual({
      ok: false,
      code: 'invalid_credentials',
    })
  })

  it('keeps a new account out until its e-mail is verified', () => {
    const email = 'new.user@labo-exemple.fr'
    expect(mockSignUp({ ...request, email }).ok).toBe(true)
    expect(mockSignIn({ email, password: request.password, remember: false })).toEqual({
      ok: false,
      code: 'account_pending_email',
    })
  })

  it('answers the same way when the address is already registered', () => {
    expect(mockSignUp({ ...request, email: 'demo@genomica.local' })).toEqual({ ok: true, value: null })
  })

  it('walks the account lifecycle like the backend', () => {
    const email = 'awa.diop@chu-fann.sn'
    const printed = linksPrinted()
    mockSignUp({ ...request, email })
    expect(mockVerifyEmail(lastToken(printed, 'verify-email'))).toEqual({ ok: true, value: null })

    const session = mockSignIn({ email, password: request.password, remember: false })
    expect(session.ok && session.value.user.status).toBe('onboarding')
    if (!session.ok) return
    const profile = { fullName: 'Awa Diop', profession: 'medical_biologist' as const, organization: 'CHU Fann', intendedUse: '' }
    const submitted = mockCompleteOnboarding(session.value.token, profile)
    expect(submitted.ok && submitted.value.status).toBe('pending_review')
    expect(mockUserForToken(session.value.token)).toBeNull() // session ended for the review

    const pending = mockAccessRequests().find((r) => r.email === email)
    expect(pending?.organization).toBe('CHU Fann')
    expect(mockDecide(pending!.id, 'approve')).toEqual({ ok: true, value: null })
    expect(mockDecide(pending!.id, 'reject')).toEqual({ ok: false, code: 'invalid_transition' })
    expect(mockSignIn({ email, password: request.password, remember: false }).ok).toBe(true)
  })

  it('uses a verification link only once', () => {
    const printed = linksPrinted()
    mockSignUp({ ...request, email: 'once@labo-exemple.fr' })
    const token = lastToken(printed, 'verify-email')
    expect(mockVerifyEmail(token).ok).toBe(true)
    expect(mockVerifyEmail(token)).toEqual({ ok: false, code: 'invalid_token' })
  })

  it('resets a password and closes the open sessions', () => {
    const printed = linksPrinted()
    const session = mockSignIn({ email: 'demo@genomica.local', password: 'genomica-demo-2026', remember: false })
    mockForgotPassword('demo@genomica.local')
    const token = lastToken(printed, 'reset-password')
    expect(mockResetPassword(token, 'another-long-password')).toEqual({ ok: true, value: null })
    if (session.ok) expect(mockUserForToken(session.value.token)).toBeNull()
    expect(mockSignIn({ email: 'demo@genomica.local', password: 'another-long-password', remember: false }).ok).toBe(true)
    mockForgotPassword('demo@genomica.local')
    mockResetPassword(lastToken(printed, 'reset-password'), 'genomica-demo-2026')
  })
})

afterEach(() => vi.restoreAllMocks())

/** The mock prints the links the backend would e-mail; capture them. */
function linksPrinted(): string[] {
  const lines: string[] = []
  vi.spyOn(console, 'info').mockImplementation((line: string) => void lines.push(line))
  return lines
}

function lastToken(lines: string[], page: string): string {
  const line = lines.filter((l) => l.includes(`/${page}?token=`)).at(-1)
  return line?.split('token=')[1] ?? ''
}
