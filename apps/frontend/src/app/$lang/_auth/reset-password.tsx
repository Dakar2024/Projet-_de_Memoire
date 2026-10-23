import { createFileRoute } from '@tanstack/react-router'
import * as z from 'zod'
import { ResetPasswordForm } from '@/features/auth/components/ResetPasswordForm'

const searchSchema = z.object({ token: z.string().catch('') })

/** Target of the link in the reset e-mail. No referrer: the token must not leak to linked pages. */
export const Route = createFileRoute('/$lang/_auth/reset-password')({
  validateSearch: searchSchema,
  head: () => ({ meta: [{ title: 'Nouveau mot de passe · Genomica' }, { name: 'referrer', content: 'no-referrer' }] }),
  component: ResetPasswordPage,
})

function ResetPasswordPage() {
  const { token } = Route.useSearch()
  return <ResetPasswordForm token={token} />
}
