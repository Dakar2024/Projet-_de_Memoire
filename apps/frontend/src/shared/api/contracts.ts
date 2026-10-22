/**
 * Types of the Genomica backend contract (apps/backend/MODELISATION_BACKEND.md).
 * The frontend only talks to that backend; it never calls the RAG API directly.
 */

export type AccountStatus = 'pending_email' | 'onboarding' | 'pending_review' | 'active' | 'rejected' | 'suspended'

export type Role = 'user' | 'admin'

export const PROFESSIONS = [
  'medical_biologist',
  'clinical_geneticist',
  'bioinformatician',
  'genetic_counselor',
  'researcher',
  'other',
] as const
export type Profession = (typeof PROFESSIONS)[number]

export type User = {
  id: string
  email: string
  fullName: string
  role: Role
  status: AccountStatus
  profession: Profession
  organization: string
}

export type SignInInput = {
  email: string
  password: string
  remember: boolean
}

/**
 * Access request, kept to the minimum as on the sign-in screen: name, profession and organisation
 * are collected after the e-mail is verified (onboarding), before the admin review.
 * One checkbox covers both the terms and the no-patient-data pledge; the backend stores both dates.
 */
export type SignUpInput = {
  email: string
  password: string
  termsAccepted: true
  noPatientDataPledge: true
}

export type PanelId = 'brca' | 'sickle'

export type PanelSummary = {
  id: PanelId
  genes: string[]
  variantCount: number
}

/** GET /api/panels — public, read from gold/analytique. */
export type PanelsResponse = {
  archive: string
  variantCount: number
  diseaseCount: number
  phenotypeCount: number
  panels: PanelSummary[]
}

/** Error body shared by every backend route. */
export type ApiErrorBody = {
  error: ApiErrorCode
  message: string
  request_id?: string
}

export type ApiErrorCode =
  | 'unauthorized'
  | 'invalid_credentials'
  | 'account_pending_email'
  | 'account_pending_review'
  | 'account_rejected'
  | 'account_suspended'
  | 'email_taken'
  | 'validation_error'
  | 'rate_limited'
  | 'unavailable'
  | 'internal'
