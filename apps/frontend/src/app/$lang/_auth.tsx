import { Outlet, createFileRoute, redirect } from '@tanstack/react-router'
import { useSuspenseQuery } from '@tanstack/react-query'
import { Trans, useLingui } from '@lingui/react/macro'
import { ArrowLeft } from 'lucide-react'
import { sessionQuery } from '@/features/auth/hooks'
import { AuthAside } from '@/features/auth/components/AuthAside'
import { safeRedirect } from '@/features/auth/redirect'
import { panelsQuery } from '@/features/landing/server'
import { Logo } from '@/shared/components/brand/Logo'
import { LocalizedLink } from '@/shared/components/LocalizedLink'

/** Split auth layout: form on the left, product recap on the right (hidden under 1024 px). */
export const Route = createFileRoute('/$lang/_auth')({
  beforeLoad: async ({ context, params, location }) => {
    const user = await context.queryClient.ensureQueryData(sessionQuery)
    if (user) {
      const target = (location.search as { redirect?: unknown }).redirect
      throw redirect({ href: safeRedirect(target, `/${params.lang}/assistant`) })
    }
  },
  loader: ({ context }) => context.queryClient.ensureQueryData(panelsQuery),
  component: AuthLayout,
})

function AuthLayout() {
  const { t } = useLingui()
  const { data } = useSuspenseQuery(panelsQuery)

  return (
    <div className="flex min-h-screen flex-wrap bg-background">
      <main className="flex min-w-0 flex-[1_1_560px] flex-col px-6 py-7">
        <div className="mx-auto flex w-full max-w-[480px] items-center justify-between gap-3">
          <LocalizedLink to="/" className="text-foreground" aria-label={t`Genomica, accueil`}>
            <Logo size={32} />
          </LocalizedLink>
          <LocalizedLink
            to="/"
            className="inline-flex min-h-11 items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" aria-hidden="true" />
            <Trans>Retour à l'accueil</Trans>
          </LocalizedLink>
        </div>
        <div className="flex flex-1 items-center justify-center py-8">
          <div className="w-full max-w-[480px]">
            <Outlet />
          </div>
        </div>
        <p className="mx-auto max-w-[480px] text-center text-xs leading-normal text-faint">
          <Trans>Aide à la consultation de bases publiques. Ne remplace pas l'interprétation clinique d'un biologiste.</Trans>
        </p>
      </main>
      <AuthAside data={data} />
    </div>
  )
}
