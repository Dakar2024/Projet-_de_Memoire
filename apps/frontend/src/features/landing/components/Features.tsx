import { Trans } from '@lingui/react/macro'
import { BarChart3, BookOpen, CircleSlash, History, MessageSquare, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { SectionHeading } from './SectionHeading'

type Feature = { icon: LucideIcon; title: ReactNode; body: ReactNode; wide?: boolean }

const FEATURES: Feature[] = [
  {
    icon: MessageSquare,
    wide: true,
    title: <Trans>Assistant en langage naturel</Trans>,
    body: (
      <Trans>
        Notation HGVS, identifiant rs, nom de protéine ou question libre : l'assistant reconnaît la forme, retrouve les
        fiches pertinentes et répond en français, avec un numéro de source sur chaque affirmation.
      </Trans>
    ),
  },
  {
    icon: BarChart3,
    title: <Trans>Explorateur analytique</Trans>,
    body: <Trans>Répartition des classifications par gène, niveau de revue, maladies et phénotypes associés.</Trans>,
  },
  {
    icon: BookOpen,
    title: <Trans>Sources citées</Trans>,
    body: <Trans>Chaque réponse liste ses fiches ClinVar : Variation ID, statut de revue en étoiles, archive consultée.</Trans>,
  },
  {
    icon: CircleSlash,
    title: <Trans>Abstention plutôt qu'invention</Trans>,
    body: (
      <Trans>
        Si ClinVar ne documente pas le point demandé, la réponse le dit. Les contrôles s'exécutent avant l'affichage.
      </Trans>
    ),
  },
  {
    icon: History,
    title: <Trans>Historique des reclassifications</Trans>,
    body: <Trans>Une classification a changé ? L'ancienne et sa date de fin sont rappelées sous la réponse.</Trans>,
  },
]

export function Features() {
  return (
    <section
      id="fonctionnalites"
      aria-labelledby="features-title"
      className="mx-auto flex max-w-[1240px] scroll-mt-20 flex-col gap-10 px-6 py-24"
    >
      <SectionHeading
        id="features-title"
        eyebrow={<Trans>Fonctionnalités</Trans>}
        title={<Trans>Deux outils, une seule source de vérité.</Trans>}
        lead={
          <Trans>
            L'assistant répond aux questions ponctuelles ; l'explorateur donne la vue d'ensemble. Les deux lisent les
            mêmes données, versionnées archive par archive.
          </Trans>
        }
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map(({ icon: Icon, title, body, wide }, i) => (
          <article
            key={i}
            className={cn(
              'flex flex-col gap-3 rounded-[18px] border border-border bg-card p-7 transition-[border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/50',
              wide && 'lg:col-span-2',
            )}
          >
            <span className="flex size-11 items-center justify-center rounded-xl bg-primary/12 text-primary">
              <Icon className="size-[22px]" aria-hidden="true" />
            </span>
            <h3 className="text-xl font-semibold tracking-[-0.01em]">{title}</h3>
            <p className="text-[15px] leading-relaxed text-muted-foreground">{body}</p>
          </article>
        ))}
      </div>
    </section>
  )
}
