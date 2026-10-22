import { describe, expect, it } from 'vitest'
import { mockSignIn, mockSignOut, mockSignUp, mockUserForToken } from './auth-store'

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
})
