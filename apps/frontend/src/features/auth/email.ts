/**
 * Consumer mailbox providers refused at sign-up: access is for professionals, identified by their
 * institution's address. Client-side hint only; the backend enforces its own allow/deny lists
 * (`allowed_email_domains` in the admin settings).
 */
const CONSUMER_DOMAINS = new Set([
  'gmail.com',
  'googlemail.com',
  'yahoo.com',
  'yahoo.fr',
  'ymail.com',
  'hotmail.com',
  'hotmail.fr',
  'outlook.com',
  'outlook.fr',
  'live.com',
  'live.fr',
  'msn.com',
  'icloud.com',
  'me.com',
  'mac.com',
  'aol.com',
  'proton.me',
  'protonmail.com',
  'gmx.com',
  'gmx.fr',
  'gmx.de',
  'yandex.com',
  'yandex.ru',
  'mail.ru',
  'mail.com',
  'zoho.com',
  'orange.fr',
  'wanadoo.fr',
  'free.fr',
  'sfr.fr',
  'neuf.fr',
  'laposte.net',
  'bbox.fr',
])

export function isProfessionalEmail(email: string): boolean {
  const at = email.lastIndexOf('@')
  if (at < 1) return false
  const domain = email.slice(at + 1).trim().toLowerCase()
  return domain.length > 0 && !CONSUMER_DOMAINS.has(domain)
}
