import { createFileRoute } from '@tanstack/react-router'
import * as z from 'zod'
import { SignInForm } from '@/features/auth/components/SignInForm'

const searchSchema = z.object({
  // Page asked for before being sent here; validated again by safeRedirect before use.
  redirect: z.string().max(2000).optional().catch(undefined),
})

export const Route = createFileRoute('/$lang/_auth/sign-in')({
  validateSearch: searchSchema,
  head: () => ({ meta: [{ title: 'Connexion · Genomica' }] }),
  component: SignInPage,
})

function SignInPage() {
  const { redirect } = Route.useSearch()
  return <SignInForm redirectTo={redirect} />
}
