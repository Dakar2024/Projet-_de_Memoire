import { createFileRoute } from '@tanstack/react-router'
import * as z from 'zod'
import { VerifyEmailStatus } from '@/features/auth/components/VerifyEmailStatus'

const searchSchema = z.object({ token: z.string().catch('') })

/** Target of the link in the verification e-mail (apps/backend/features/auth/emails.py). */
export const Route = createFileRoute('/$lang/_auth/verify-email')({
  validateSearch: searchSchema,
  head: () => ({ meta: [{ title: 'Confirmation de l’adresse · Genomica' }, { name: 'referrer', content: 'no-referrer' }] }),
  component: VerifyEmailPage,
})

function VerifyEmailPage() {
  const { token } = Route.useSearch()
  return <VerifyEmailStatus token={token} />
}
