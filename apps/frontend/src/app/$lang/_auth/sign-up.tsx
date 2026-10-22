import { createFileRoute } from '@tanstack/react-router'
import { SignUpForm } from '@/features/auth/components/SignUpForm'

export const Route = createFileRoute('/$lang/_auth/sign-up')({
  head: () => ({ meta: [{ title: 'Demande d’accès · Genomica' }] }),
  component: SignUpForm,
})
