import { createFileRoute } from '@tanstack/react-router'
import { useSuspenseQuery } from '@tanstack/react-query'
import { OnboardingForm } from '@/features/auth/components/OnboardingForm'
import { sessionQuery } from '@/features/auth/hooks'

/** Reached only by an `onboarding` session: the _auth layout sends everyone else away. */
export const Route = createFileRoute('/$lang/_auth/onboarding')({
  head: () => ({ meta: [{ title: 'Votre profil · Genomica' }] }),
  component: OnboardingPage,
})

function OnboardingPage() {
  const { data: user } = useSuspenseQuery(sessionQuery)
  return <OnboardingForm email={user?.email ?? ''} />
}
