import { Trans } from '@lingui/react/macro'
import { SectionHeading } from './SectionHeading'

const STEPS = [
  {
    title: <Trans>Collecte</Trans>,
    body: (
      <Trans>
        ClinVar, NCBI Gene, MedGen, HPO et RefSeq, téléchargés chaque mois. La copie brute est conservée telle quelle.
      </Trans>
    ),
  },
  {
    title: <Trans>Normalisation</Trans>,
    body: (
      <Trans>Nettoyage, dédoublonnage, liens variant–gène–maladie–phénotype, historique des classifications.</Trans>
    ),
  },
  {
    title: <Trans>Contrôle qualité</Trans>,
    body: <Trans>Une incohérence entre étapes arrête la mise à jour : la base consultée n'est jamais partielle.</Trans>,
  },
  {
    title: <Trans>Réponse sourcée</Trans>,
    body: (
      <Trans>
        Recherche sémantique et par identifiant, génération contrainte aux fiches retrouvées, vérifications avant
        affichage.
      </Trans>
    ),
  },
]

export function Method() {
  return (
    <section id="methode" aria-labelledby="method-title" className="scroll-mt-20 border-y border-border bg-card">
      <div className="mx-auto flex max-w-[1240px] flex-col gap-12 px-6 py-24">
        <SectionHeading
          id="method-title"
          eyebrow={<Trans>Méthode</Trans>}
          title={<Trans>De la base publique à la réponse, chaque étape est tracée.</Trans>}
        />
        <ol className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,250px),1fr))] gap-7">
          {STEPS.map((step, i) => (
            <li key={i} className="flex flex-col gap-3.5">
              <span
                className="flex size-9 items-center justify-center rounded-full bg-primary font-mono text-[13px] font-semibold text-primary-foreground"
                aria-hidden="true"
              >
                {String(i + 1).padStart(2, '0')}
              </span>
              <h3 className="text-lg font-semibold">{step.title}</h3>
              <p className="text-[15px] leading-relaxed text-muted-foreground">{step.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
