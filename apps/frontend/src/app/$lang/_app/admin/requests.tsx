import { createFileRoute, notFound } from '@tanstack/react-router'
import { Trans } from '@lingui/react/macro'
import { ArrowLeft } from 'lucide-react'
import { AccessRequests } from '@/features/admin/components/AccessRequests'
import { accessRequestsQuery } from '@/features/admin/hooks'
import { Logo } from '@/shared/components/brand/Logo'
import { LocalizedLink } from '@/shared/components/LocalizedLink'

/**
 * Minimal admin page, linked from the "new access request" e-mail. The full admin area comes with
 * the admin step; the backend checks the role on every call, this guard only avoids a dead page.
 */
export const Route = createFileRoute('/$lang/_app/admin/requests')({
  beforeLoad: ({ context }) => {
    if (context.user.role !== 'admin') throw notFound()
  },
  loader: ({ context }) => context.queryClient.ensureQueryData(accessRequestsQuery),
  head: () => ({ meta: [{ title: 'Demandes d’accès · Genomica' }] }),
  component: AdminRequestsPage,
})

function AdminRequestsPage() {
  return (
    <div className="min-h-dvh bg-background">
      <header className="flex items-center justify-between border-b border-border px-6 py-3">
        <Logo size={26} />
        <LocalizedLink
          to="/assistant"
          className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" aria-hidden="true" />
          <Trans>Retour à l'assistant</Trans>
        </LocalizedLink>
      </header>
      <main className="mx-auto w-full max-w-[760px] px-4 py-10 sm:px-6">
        <AccessRequests />
      </main>
    </div>
  )
}
