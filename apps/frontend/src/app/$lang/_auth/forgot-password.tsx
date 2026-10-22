import { createFileRoute } from '@tanstack/react-router'
import { ForgotPasswordForm } from '@/features/auth/components/ForgotPasswordForm'

export const Route = createFileRoute('/$lang/_auth/forgot-password')({
  head: () => ({ meta: [{ title: 'Mot de passe oublié · Genomica' }] }),
  component: ForgotPasswordForm,
})
