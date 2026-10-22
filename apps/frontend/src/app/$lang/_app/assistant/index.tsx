import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Trans } from '@lingui/react/macro'
import { LogOut } from 'lucide-react'
import { useSignOut } from '@/features/auth/hooks'
import { Logo } from '@/shared/components/brand/Logo'
import { ThemeToggle } from '@/shared/components/ThemeToggle'
import { Button } from '@/shared/components/ui/button'

export const Route = createFileRoute('/$lang/_app/assistant/')({
  head: () => ({ meta: [{ title: 'Assistant · Genomica' }] }),
  component: AssistantPlaceholder,
})

/** Temporary landing spot after sign-in; replaced by the chat interface in the next iteration. */
function AssistantPlaceholder() {
  const { user } = Route.useRouteContext()
  const { lang } = Route.useParams()
  const navigate = useNavigate()
  const signOut = useSignOut()

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center gap-3 border-b border-border px-6 py-3">
        <Logo size={28} />
        <span className="ml-auto text-sm text-muted-foreground">{user.fullName}</span>
        <ThemeToggle />
        <Button
          variant="outline"
          size="lg"
          className="h-11"
          disabled={signOut.isPending}
          onClick={() =>
            signOut.mutate(undefined, { onSuccess: () => navigate({ to: '/$lang/sign-in', params: { lang } }) })
          }
        >
          <LogOut aria-hidden="true" />
          <Trans>Se déconnecter</Trans>
        </Button>
      </header>
      <main className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
        <h1 className="text-3xl font-medium tracking-[-0.02em]">
          <Trans>Quel variant examinons-nous aujourd'hui ?</Trans>
        </h1>
        <p className="text-muted-foreground">
          <Trans>L'interface de l'assistant arrive à la prochaine itération.</Trans>
        </p>
      </main>
    </div>
  )
}
