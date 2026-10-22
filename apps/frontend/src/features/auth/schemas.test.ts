import { describe, expect, it } from 'vitest'
import { passwordStrength, signUpSchema } from './schemas'

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

describe('signUpSchema', () => {
  const valid = {
    firstName: 'Awa',
    lastName: 'Diop',
    email: 'a.diop@chu-exemple.fr',
    profession: 'medical_biologist',
    organization: 'CHU',
    password: 'Abcdefghijk1!',
    noPatientDataPledge: true,
    termsAccepted: true,
  }

  it('accepts a complete request', () => {
    expect(signUpSchema.safeParse(valid).success).toBe(true)
  })

  it('requires both pledges', () => {
    const result = signUpSchema.safeParse({ ...valid, noPatientDataPledge: false, termsAccepted: false })
    expect(result.success).toBe(false)
    const fields = result.error?.issues.map((i) => i.path[0])
    expect(fields).toEqual(expect.arrayContaining(['noPatientDataPledge', 'termsAccepted']))
  })

  it('rejects a short password and an unknown profession', () => {
    const result = signUpSchema.safeParse({ ...valid, password: 'short', profession: 'astronaut' })
    expect(result.error?.issues.map((i) => i.path[0]).sort()).toEqual(['password', 'profession'])
  })
})
