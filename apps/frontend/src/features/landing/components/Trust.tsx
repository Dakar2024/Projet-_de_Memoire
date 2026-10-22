import { Trans } from '@lingui/react/macro'
import { Lock, ShieldCheck, TriangleAlert } from 'lucide-react'
import { LocalizedLink } from '@/shared/components/LocalizedLink'
import { buttonVariants } from '@/shared/components/ui/button'
import { cn } from '@/lib/utils'

const POINTS = [
  {
    icon: ShieldCheck,
    title: <Trans>Aucune donnée patient</Trans>,
    body: (
      <Trans>
        L'outil interroge des bases publiques. Ne saisissez jamais d'information permettant d'identifier une personne.
      </Trans>
    ),
  },
  {
    icon: Lock,
    title: <Trans>Questions non journalisées</Trans>,
    body: <Trans>Les journaux techniques ne contiennent ni la question, ni la réponse, ni aucune clé.</Trans>,
  },
  {
    icon: TriangleAlert,
    title: <Trans>Aide, pas diagnostic</Trans>,
    body: (
      <Trans>Genomica restitue les classifications déposées ; l'interprétation clinique reste l'acte du biologiste.</Trans>
    ),
  },
]

export function Trust() {
  return (
    <section id="fiabilite" aria-label="Fiabilité" className="mx-auto max-w-[1240px] scroll-mt-20 px-6 pb-24">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,260px),1fr))] gap-8 rounded-[18px] border border-border bg-[color-mix(in_oklab,var(--primary)_6%,var(--card))] p-10">
        {POINTS.map(({ icon: Icon, title, body }, i) => (
          <div key={i} className="flex gap-3.5">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary/12 text-primary">
              <Icon className="size-[22px]" aria-hidden="true" />
            </span>
            <div className="flex flex-col gap-1.5">
              <h3 className="text-[17px] font-semibold">{title}</h3>
              <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

export function FinalCta() {
  return (
    <section className="mx-auto max-w-[1240px] px-6 pb-24">
      <div className="flex flex-col items-center gap-5 rounded-3xl bg-foreground px-10 py-16 text-center text-background">
        <h2 className="max-w-[720px] text-[clamp(28px,3.4vw,42px)] font-semibold leading-[1.1] tracking-[-0.03em]">
          <Trans>Rejoignez les équipes qui interrogent ClinVar en langage naturel.</Trans>
        </h2>
        <p className="max-w-[560px] text-base leading-relaxed opacity-75">
          <Trans>L'accès est réservé aux professionnels. Chaque demande est examinée par un administrateur.</Trans>
        </p>
        <LocalizedLink to="/sign-up" className={cn(buttonVariants({ size: 'lg' }), 'h-[50px] px-7 text-[15px]')}>
          <Trans>Demander un accès</Trans>
        </LocalizedLink>
      </div>
    </section>
  )
}

export function SiteFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-[1240px] flex-wrap items-center justify-between gap-x-8 gap-y-4 px-6 py-8 text-[13px] text-muted-foreground">
        <p>
          <Trans>
            Genomica — aide à la consultation de ClinVar, MedGen, HPO et NCBI Gene. Ne remplace pas l'interprétation
            clinique d'un biologiste.
          </Trans>
        </p>
        <nav className="flex gap-5" aria-label="Liens légaux">
          <a href="#fiabilite" className="hover:text-foreground">
            <Trans>Confidentialité</Trans>
          </a>
          <a href="#fiabilite" className="hover:text-foreground">
            <Trans>Conditions d'utilisation</Trans>
          </a>
          <a href="#methode" className="hover:text-foreground">
            <Trans>Sources de données</Trans>
          </a>
        </nav>
      </div>
    </footer>
  )
}
