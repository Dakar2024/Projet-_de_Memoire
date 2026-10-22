import { Outlet, createFileRoute, redirect } from '@tanstack/react-router'
import { useSuspenseQuery } from '@tanstack/react-query'
import { Trans, useLingui } from '@lingui/react/macro'
import { sessionQuery } from '@/features/auth/hooks'
import { AuthArt } from '@/features/auth/components/AuthArt'
import { safeRedirect } from '@/features/auth/redirect'
import { panelsQuery } from '@/features/landing/server'
import { Logo } from '@/shared/components/brand/Logo'
import { LocalizedLink } from '@/shared/components/LocalizedLink'

/**
 * Auth layout: logo and form on one side, the illustrated panel on the other.
 * Under 1024 px the panel moves below the form instead of disappearing.
 */
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
      <main className="flex min-w-0 flex-[1_1_560px] flex-col px-8 pb-10 pt-7">
        <LocalizedLink
          to="/"
          className="inline-flex min-h-11 items-center self-start text-foreground"
          aria-label={t`Genomica, accueil`}
        >
          <Logo size={30} />
        </LocalizedLink>
        <div className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-[440px]">
            <Outlet />
          </div>
        </div>
        <p className="mx-auto max-w-[440px] text-center text-xs leading-normal text-faint">
          <Trans>Aide à la consultation de bases publiques. Ne remplace pas l'interprétation clinique d'un biologiste.</Trans>
        </p>
      </main>
      <AuthArt data={data} />
    </div>
  )
}
