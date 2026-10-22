import type { ApiErrorCode, SignInInput, SignUpInput, User } from '@/shared/api/contracts'

/**
 * In-memory stand-in for the backend `auth` feature, used only when VITE_USE_MOCKS=true.
 * It lives on the server (inside server functions) so SSR and the browser see the same session.
 * Passwords are compared in clear text: development data only, reset at every restart.
 */

type StoredUser = User & { password: string }

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
    },
  ].map((u) => [u.email, u as StoredUser]),
)

const sessions = new Map<string, string>()

const STATUS_ERRORS: Partial<Record<User['status'], ApiErrorCode>> = {
  pending_email: 'account_pending_email',
  pending_review: 'account_pending_review',
  rejected: 'account_rejected',
  suspended: 'account_suspended',
}

function publicUser({ password: _password, ...user }: StoredUser): User {
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
      fullName: `${input.firstName} ${input.lastName}`.trim(),
      role: 'user',
      status: 'pending_email',
      profession: input.profession,
      organization: input.organization,
      password: input.password,
    })
  }
  return { ok: true, value: null }
}

export function mockUserForToken(token: string | undefined): User | null {
  if (!token) return null
  const email = sessions.get(token)
  const stored = email ? users.get(email) : undefined
  return stored && stored.status === 'active' ? publicUser(stored) : null
}

export function mockSignOut(token: string | undefined): void {
  if (token) sessions.delete(token)
}
