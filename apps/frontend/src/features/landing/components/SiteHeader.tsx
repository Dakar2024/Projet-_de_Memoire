import { Trans, useLingui } from '@lingui/react/macro'
import { Logo } from '@/shared/components/brand/Logo'
import { LocalizedLink } from '@/shared/components/LocalizedLink'
import LanguageSwitcher from '@/shared/components/LanguageSwitcher'
import { ThemeToggle } from '@/shared/components/ThemeToggle'
import { buttonVariants } from '@/shared/components/ui/button'
import { cn } from '@/lib/utils'

const NAV = [
  { href: '#fonctionnalites', key: 'features' },
  { href: '#donnees', key: 'data' },
  { href: '#methode', key: 'method' },
  { href: '#fiabilite', key: 'trust' },
] as const

export function SiteHeader() {
  const { t } = useLingui()
  const labels = {
    features: t`Fonctionnalités`,
    data: t`Données`,
    method: t`Méthode`,
    trust: t`Fiabilité`,
  }

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-background/80 backdrop-blur-md">
      <nav
        aria-label={t`Navigation principale`}
        className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-4 px-6 py-3"
      >
        <LocalizedLink to="/" className="text-foreground" aria-label={t`Genomica, accueil`}>
          <Logo size={34} />
        </LocalizedLink>
        <div className="ml-6 hidden gap-1 md:flex">
          {NAV.map((item) => (
            <a
              key={item.key}
              href={item.href}
              className="rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              {labels[item.key]}
            </a>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <LanguageSwitcher />
          <ThemeToggle />
          <LocalizedLink to="/sign-in" className={cn(buttonVariants({ variant: 'outline', size: 'lg' }), 'h-11')}>
            <Trans>Se connecter</Trans>
          </LocalizedLink>
          <LocalizedLink to="/sign-up" className={cn(buttonVariants({ size: 'lg' }), 'hidden h-11 md:inline-flex')}>
            <Trans>Demander un accès</Trans>
          </LocalizedLink>
        </div>
      </nav>
    </header>
  )
}
