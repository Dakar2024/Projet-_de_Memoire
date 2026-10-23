import { describe, expect, it } from 'vitest'
import { onboardingSchema, passwordStrength, resetPasswordFormSchema, signUpFormSchema, signUpSchema } from './schemas'

describe('passwordStrength', () => {
  it.each([
    ['', 0],
    ['abc', 1],
    ['abcdefghijkl', 1],
    ['Abcdefghijkl', 2],
    ['Abcdefghijk1', 3],
    ['Abcdefghijk1!', 4],
    ['abcdefghijklmnop', 2],
  ])('scores %j as %i', (password, expected) => {
    expect(passwordStrength(password)).toBe(expected)
  })
})

describe('signUpFormSchema', () => {
  const valid = {
    email: 'a.diop@chu-exemple.fr',
    password: 'Abcdefghijk1!',
    passwordConfirm: 'Abcdefghijk1!',
    termsAccepted: true,
    noPatientDataPledge: true,
  }
  const failingFields = (input: object) =>
    signUpFormSchema.safeParse(input).error?.issues.map((i) => String(i.path[0])).sort() ?? []

  it('accepts a complete request', () => {
    expect(signUpFormSchema.safeParse(valid).success).toBe(true)
  })

  it('refuses a consumer mailbox', () => {
    expect(failingFields({ ...valid, email: 'a.diop@gmail.com' })).toEqual(['email'])
  })

  it('requires the confirmation to match', () => {
    expect(failingFields({ ...valid, passwordConfirm: 'Abcdefghijk1?' })).toEqual(['passwordConfirm'])
  })

  it('requires the consent and a long enough password', () => {
    expect(failingFields({ ...valid, password: 'short', passwordConfirm: 'short', termsAccepted: false })).toEqual([
      'password',
      'termsAccepted',
    ])
  })

  it('never sends the confirmation to the backend', () => {
    const parsed = signUpSchema.parse(valid)
    expect(parsed).not.toHaveProperty('passwordConfirm')
  })
})

describe('onboardingSchema', () => {
  const profile = { fullName: ' Awa Diop ', profession: 'medical_biologist', organization: 'CHU Fann', intendedUse: '' }

  it('trims and accepts a complete profile', () => {
    const parsed = onboardingSchema.safeParse(profile)
    expect(parsed.success && parsed.data.fullName).toBe('Awa Diop')
  })

  it('requires a known profession, a name and an organisation', () => {
    expect(onboardingSchema.safeParse({ ...profile, profession: 'astronaut' }).success).toBe(false)
    expect(onboardingSchema.safeParse({ ...profile, fullName: '  ' }).success).toBe(false)
    expect(onboardingSchema.safeParse({ ...profile, organization: '' }).success).toBe(false)
  })
})

describe('resetPasswordFormSchema', () => {
  const token = 'x'.repeat(43)

  it('requires a token, a long enough password and the same confirmation', () => {
    const ok = { token, password: 'correct-horse-battery', passwordConfirm: 'correct-horse-battery' }
    expect(resetPasswordFormSchema.safeParse(ok).success).toBe(true)
    expect(resetPasswordFormSchema.safeParse({ ...ok, token: '' }).success).toBe(false)
    expect(resetPasswordFormSchema.safeParse({ ...ok, password: 'short', passwordConfirm: 'short' }).success).toBe(false)
    expect(resetPasswordFormSchema.safeParse({ ...ok, passwordConfirm: 'different-password' }).success).toBe(false)
  })
})
