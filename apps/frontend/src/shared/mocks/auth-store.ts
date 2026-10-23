import type { AccessRequest, ApiErrorCode, OnboardingInput, SignInInput, SignUpInput, User } from '@/shared/api/contracts'

/**
 * In-memory stand-in for the backend `auth` feature, used only when VITE_USE_MOCKS=true.
 * It lives on the server (inside server functions) so SSR and the browser see the same session.
 * Passwords are compared in clear text: development data only, reset at every restart.
 * The links the real backend e-mails (verification, reset) are printed on the server console.
 */

type StoredUser = User & { password: string; createdAt: string }

const DEMO_PASSWORD = 'genomica-demo-2026'

const users = new Map<string, StoredUser>(
  [
    {
      id: 'u-demo',
      email: 'demo@genomica.local',
      fullName: 'A. Diop',
      role: 'user',
      status: 'active',
      profession: 'medical_biologist',
      organization: 'CHU [établissement]',
      password: DEMO_PASSWORD,
      createdAt: '2026-10-01T09:00:00Z',
    },
    {
      id: 'u-admin',
      email: 'admin@genomica.local',
      fullName: 'Administrateur',
      role: 'admin',
      status: 'active',
      profession: 'bioinformatician',
      organization: 'Genomica',
      password: DEMO_PASSWORD,
      createdAt: '2026-10-01T09:00:00Z',
    },
  ].map((u) => [u.email, u as StoredUser]),
)

const sessions = new Map<string, string>()
// One-time links: token -> e-mail.
const verificationTokens = new Map<string, string>()
const resetTokens = new Map<string, string>()

const SIGN_IN_STATUSES: ReadonlySet<User['status']> = new Set(['active', 'onboarding'])

const STATUS_ERRORS: Partial<Record<User['status'], ApiErrorCode>> = {
  pending_email: 'account_pending_email',
  pending_review: 'account_pending_review',
  rejected: 'account_rejected',
  suspended: 'account_suspended',
}

function publicUser({ password: _password, createdAt: _createdAt, ...user }: StoredUser): User {
  return user
}

export type MockResult<T> = { ok: true; value: T } | { ok: false; code: ApiErrorCode }

export function mockSignIn(input: SignInInput): MockResult<{ user: User; token: string }> {
  const stored = users.get(input.email.trim().toLowerCase())
  if (!stored || stored.password !== input.password) return { ok: false, code: 'invalid_credentials' }
  const blocked = STATUS_ERRORS[stored.status]
  if (blocked) return { ok: false, code: blocked }
  const token = crypto.randomUUID()
  sessions.set(token, stored.email)
  return { ok: true, value: { user: publicUser(stored), token } }
}

export function mockSignUp(input: SignUpInput): MockResult<null> {
  const email = input.email.trim().toLowerCase()
  // Same answer whether the address exists or not, as the real backend does.
  if (!users.has(email)) {
    users.set(email, {
      id: crypto.randomUUID(),
      email,
      // Filled in during onboarding, after the e-mail check.
      fullName: '',
      role: 'user',
      status: 'pending_email',
      profession: null,
      organization: null,
      password: input.password,
      createdAt: new Date().toISOString(),
    })
  }
  if (users.get(email)?.status === 'pending_email') issueLink(verificationTokens, email, 'verify-email')
  return { ok: true, value: null }
}

export function mockUserForToken(token: string | undefined): User | null {
  if (!token) return null
  const email = sessions.get(token)
  const stored = email ? users.get(email) : undefined
  return stored && SIGN_IN_STATUSES.has(stored.status) ? publicUser(stored) : null
}

function issueLink(store: Map<string, string>, email: string, page: string): void {
  const token = crypto.randomUUID()
  store.set(token, email)
  console.info(`[mock e-mail] ${email}: /fr/${page}?token=${token}`)
}

function consume(store: Map<string, string>, token: string): StoredUser | undefined {
  const email = store.get(token)
  store.delete(token)
  return email ? users.get(email) : undefined
}

export function mockResendVerification(email: string): void {
  const normalized = email.trim().toLowerCase()
  if (users.get(normalized)?.status === 'pending_email') issueLink(verificationTokens, normalized, 'verify-email')
}

export function mockVerifyEmail(token: string): MockResult<null> {
  const stored = consume(verificationTokens, token)
  if (!stored || stored.status !== 'pending_email') return { ok: false, code: 'invalid_token' }
  stored.status = 'onboarding'
  return { ok: true, value: null }
}

export function mockCompleteOnboarding(token: string | undefined, input: OnboardingInput): MockResult<User> {
  const email = token ? sessions.get(token) : undefined
  const stored = email ? users.get(email) : undefined
  if (!stored || stored.status !== 'onboarding') return { ok: false, code: 'forbidden' }
  Object.assign(stored, {
    fullName: input.fullName,
    profession: input.profession,
    organization: input.organization,
    status: 'pending_review',
  })
  if (token) sessions.delete(token)
  return { ok: true, value: publicUser(stored) }
}

export function mockForgotPassword(email: string): void {
  const normalized = email.trim().toLowerCase()
  const stored = users.get(normalized)
  if (stored && SIGN_IN_STATUSES.has(stored.status)) issueLink(resetTokens, normalized, 'reset-password')
}

export function mockResetPassword(token: string, password: string): MockResult<null> {
  const stored = consume(resetTokens, token)
  if (!stored) return { ok: false, code: 'invalid_token' }
  stored.password = password
  for (const [session, email] of sessions) if (email === stored.email) sessions.delete(session)
  return { ok: true, value: null }
}

export function mockAccessRequests(): AccessRequest[] {
  return [...users.values()]
    .filter((u) => u.status === 'pending_review')
    .map((u) => ({
      id: u.id,
      email: u.email,
      fullName: u.fullName,
      profession: u.profession,
      organization: u.organization,
      intendedUse: null,
      emailVerifiedAt: u.createdAt,
      createdAt: u.createdAt,
    }))
}

export function mockDecide(id: string, decision: 'approve' | 'reject'): MockResult<null> {
  const stored = [...users.values()].find((u) => u.id === id)
  if (!stored) return { ok: false, code: 'not_found' }
  if (stored.status !== 'pending_review') return { ok: false, code: 'invalid_transition' }
  stored.status = decision === 'approve' ? 'active' : 'rejected'
  return { ok: true, value: null }
}

export function mockSignOut(token: string | undefined): void {
  if (token) sessions.delete(token)
}
