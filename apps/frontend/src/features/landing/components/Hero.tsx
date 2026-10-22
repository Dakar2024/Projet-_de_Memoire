import { Trans } from '@lingui/react/macro'
import { ArrowRight, Check } from 'lucide-react'
import { LocalizedLink } from '@/shared/components/LocalizedLink'
import { buttonVariants } from '@/shared/components/ui/button'
import { cn } from '@/lib/utils'
import { DnaHelix, FloatingDna } from './DnaHelix'

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div
        className="pointer-events-none absolute -right-32 -top-44 size-[620px] rounded-full blur-[10px]"
        style={{ background: 'radial-gradient(closest-side, color-mix(in oklab, var(--primary) 22%, transparent), transparent)' }}
        aria-hidden="true"
      />
      <FloatingDna size={34} style={{ top: 90, left: '3%', animationDelay: '-1s' }} />
      <FloatingDna size={26} style={{ bottom: 70, left: '40%', animationDelay: '-4s' }} />
      <FloatingDna size={40} style={{ top: 46, right: '4%', animationDelay: '-6s' }} />
      <FloatingDna size={22} style={{ bottom: 40, right: '6%', animationDelay: '-2.5s' }} />

      <div className="relative z-[1] mx-auto grid max-w-[1240px] grid-cols-1 items-start gap-12 px-6 pb-22 pt-10 lg:grid-cols-2">
        <div className="flex flex-col gap-7 lg:pt-12">
          <h1 className="text-[clamp(40px,5.4vw,68px)] font-semibold leading-[1.02] tracking-[-0.035em]">
            <Trans>
              Les variants de l'ADN, expliqués <span className="text-primary">avec leurs sources.</span>
            </Trans>
          </h1>
          <p className="max-w-[560px] text-[19px] leading-relaxed text-muted-foreground">
            <Trans>
              Posez votre question en langage naturel. Genomica cherche dans ClinVar, MedGen, HPO et NCBI Gene, répond
              en français et relie chaque affirmation à sa fiche d'origine. Quand la donnée n'existe pas, l'assistant le
              dit plutôt que d'inventer.
            </Trans>
          </p>
          <div className="flex flex-wrap gap-3">
            <LocalizedLink to="/sign-up" className={cn(buttonVariants({ size: 'lg' }), 'h-[50px] px-6 text-[15px]')}>
              <Trans>Demander un accès</Trans>
              <ArrowRight />
            </LocalizedLink>
            <a href="#apercu" className={cn(buttonVariants({ variant: 'outline', size: 'lg' }), 'h-[50px] px-6 text-[15px]')}>
              <Trans>Voir un exemple de réponse</Trans>
            </a>
          </div>
          <ul className="flex flex-wrap gap-5 text-[13px] text-muted-foreground">
            {[<Trans key="a">Sources citées</Trans>, <Trans key="b">Aucune donnée patient requise</Trans>, <Trans key="c">Mise à jour mensuelle</Trans>].map(
              (label, i) => (
                <li key={i} className="inline-flex items-center gap-2">
                  <Check className="size-4" aria-hidden="true" />
                  {label}
                </li>
              ),
            )}
          </ul>
        </div>

        <div className="relative flex min-h-[560px] items-center justify-center self-center max-md:scale-90">
          <DnaHelix />
          <div className="absolute left-0 top-9 flex max-w-[230px] flex-col gap-1.5 rounded-2xl border border-border bg-card px-4 py-3.5 shadow-elevated">
            <span className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">
              <Trans>Survolez l'hélice</Trans>
            </span>
            <span className="text-[13px] leading-snug text-muted-foreground">
              <Trans>
                Séquence codante de <span className="font-mono text-foreground">HBB</span>, positions c.1 à c.24.
              </Trans>
            </span>
          </div>
          <div className="absolute bottom-7 right-0 flex items-center gap-3 rounded-2xl border border-border bg-card px-4 py-3.5 shadow-elevated">
            <span className="size-2.5 rounded-full bg-sig-p" aria-hidden="true" />
            <div className="flex flex-col gap-1">
              <span className="font-mono text-[13px]">HBB c.20A&gt;T · p.Glu7Val</span>
              <span className="text-xs text-muted-foreground">
                <Trans>Pathogène · ClinVar VCV 15333</Trans>
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
