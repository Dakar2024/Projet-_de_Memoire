import { Trans } from '@lingui/react/macro'
import { LogoMark } from './brand/LogoMark'
import { LocalizedLink } from './LocalizedLink'
import { buttonVariants } from './ui/button'

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-5 px-6 text-center">
      <LogoMark size={48} />
      <p className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">404</p>
      <h1 className="text-3xl font-semibold tracking-[-0.02em]">
        <Trans>Cette page n'existe pas.</Trans>
      </h1>
      <p className="max-w-md text-muted-foreground">
        <Trans>Le lien est peut-être incomplet, ou la page a été déplacée.</Trans>
      </p>
      <LocalizedLink to="/" className={buttonVariants({ size: 'lg' })}>
        <Trans>Retour à l'accueil</Trans>
      </LocalizedLink>
    </main>
  )
}
