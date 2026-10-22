import { msg } from '@lingui/core/macro'
import type { MessageDescriptor } from '@lingui/core'
import type { ApiErrorCode } from './contracts'

/** Error raised for any non-2xx backend answer; `code` drives the message shown to the user. */
export class ApiError extends Error {
  constructor(
    readonly code: ApiErrorCode,
    readonly status: number,
    readonly retryAfterS?: number,
  ) {
    super(code)
    this.name = 'ApiError'
  }
}

const MESSAGES: Record<ApiErrorCode, MessageDescriptor> = {
  unauthorized: msg`Votre session a expiré. Reconnectez-vous.`,
  invalid_credentials: msg`E-mail ou mot de passe incorrect.`,
  account_pending_email: msg`Confirmez d'abord votre adresse avec le lien reçu par e-mail.`,
  account_pending_review: msg`Votre demande d'accès est en cours d'examen.`,
  account_rejected: msg`Votre demande d'accès n'a pas été acceptée.`,
  account_suspended: msg`Ce compte est suspendu. Contactez un administrateur.`,
  email_taken: msg`Une demande existe déjà pour cette adresse.`,
  validation_error: msg`Certains champs sont invalides.`,
  rate_limited: msg`Trop de tentatives. Réessayez dans quelques minutes.`,
  unavailable: msg`Service momentanément indisponible. Réessayez.`,
  internal: msg`Erreur inattendue. Elle a été signalée.`,
}

/** Message descriptor for any thrown value; unknown errors fall back to `internal`. */
export function errorMessage(error: unknown): MessageDescriptor {
  if (error instanceof ApiError) return MESSAGES[error.code]
  return MESSAGES.internal
}

export function isApiErrorCode(value: unknown): value is ApiErrorCode {
  return typeof value === 'string' && value in MESSAGES
}
