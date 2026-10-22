import * as z from 'zod'
import { PROFESSIONS } from '@/shared/api/contracts'

export const PASSWORD_MIN_LENGTH = 12

export const signInSchema = z.object({
  email: z.email(),
  password: z.string().min(1),
  remember: z.boolean(),
})

export const signUpSchema = z.object({
  firstName: z.string().trim().min(1).max(100),
  lastName: z.string().trim().min(1).max(100),
  email: z.email(),
  profession: z.enum(PROFESSIONS),
  organization: z.string().trim().min(2).max(200),
  password: z.string().min(PASSWORD_MIN_LENGTH).max(128),
  intendedUse: z.string().trim().max(500).optional(),
  noPatientDataPledge: z.literal(true),
  termsAccepted: z.literal(true),
})

export const emailSchema = z.object({ email: z.email() })

/**
 * Password strength from 0 (empty) to 4, shown as a four-segment meter.
 * Advisory only: the backend enforces the real rule (length).
 */
export function passwordStrength(password: string): 0 | 1 | 2 | 3 | 4 {
  if (!password) return 0
  let score = 0
  if (password.length >= PASSWORD_MIN_LENGTH) score++
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score++
  if (/\d/.test(password)) score++
  if (/[^A-Za-z0-9]/.test(password) || password.length >= 16) score++
  return Math.max(1, score) as 1 | 2 | 3 | 4
}
