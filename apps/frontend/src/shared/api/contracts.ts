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
  /** Null until onboarding is completed. */
  profession: Profession | null
  organization: string | null
}

/** Profile completed after the e-mail check, before the admin review (PUT /api/me/onboarding). */
export type OnboardingInput = {
  fullName: string
  profession: Profession
  organization: string
  intendedUse: string
}

/** A completed profile waiting for an admin decision (GET /api/admin/requests). */
export type AccessRequest = {
  id: string
  email: string
  fullName: string
  profession: Profession | null
  organization: string | null
  intendedUse: string | null
  emailVerifiedAt: string | null
  createdAt: string
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

/**
 * Assistant answer statuses. The first four are the RAG generation schema; `unverifiable` is set by
 * the RAG itself when the generated text fails its deterministic checks (RAG/src/generation/answer.py).
 */
export type AnswerStatus = 'answered' | 'partial' | 'not_in_sources' | 'out_of_scope' | 'unverifiable'

export type ScopeReason = 'counting' | 'acmg' | 'frequency' | 'clinical_advice' | 'other' | 'gene_out_of_panel'

/** Frozen copy of a cited ClinVar record, in citation order (`message_sources`). */
export type AnswerSource = {
  rank: number
  gene: string | null
  variant: string | null
  protein: string | null
  significance: string | null
  significanceFr: string | null
  reviewStatus: string | null
  stars: number | null
  clinvarVariationId: string | null
  clinvarUrl: string | null
  archive: string | null
  previousSignificanceFr: string | null
  previousUntil: string | null
}

export type UserMessage = {
  id: string
  role: 'user'
  content: string
  createdAt: string
}

export type AssistantMessage = {
  id: string
  role: 'assistant'
  content: string
  createdAt: string
  status: AnswerStatus
  scopeReason: ScopeReason | null
  history: string[]
  sources: AnswerSource[]
  disclaimer: string
}

export type ChatMessage = UserMessage | AssistantMessage

export type ConversationSummary = {
  id: string
  title: string
  updatedAt: string
  pinned?: boolean
}

/** GET /api/assistant/conversations — newest first, keyset pagination. */
export type ConversationPage = {
  items: ConversationSummary[]
  nextCursor: string | null
}

/** GET /api/assistant/conversations/{id} */
export type Conversation = ConversationSummary & {
  panel: PanelId | null
  messages: ChatMessage[]
}

/** POST /api/assistant/questions — the RAG has no memory: each question is sent alone. */
export type AskQuestionInput = {
  conversationId?: string
  question: string
  panel?: PanelId
}

export type AskQuestionResponse = {
  conversationId: string
  message: AssistantMessage
  quotaRemaining: number
}

/** Error body shared by every backend route. */
export type ApiErrorBody = {
  error: ApiErrorCode
  message: string
  request_id?: string
}

/** Every `error` value the backend sends (apps/backend/README.md). */
export type ApiErrorCode =
  | 'unauthorized'
  | 'forbidden'
  | 'invalid_credentials'
  | 'invalid_password'
  | 'account_pending_email'
  | 'account_pending_review'
  | 'account_rejected'
  | 'account_suspended'
  | 'email_not_professional'
  | 'registration_closed'
  | 'invalid_token'
  | 'invalid_transition'
  | 'last_admin'
  | 'validation_error'
  | 'rate_limited'
  | 'not_found'
  | 'quota_exceeded'
  | 'budget_exhausted'
  | 'panel_filter_unavailable'
  | 'assistant_busy'
  | 'assistant_unavailable'
  | 'index_building'
  | 'unavailable'
  | 'internal'
