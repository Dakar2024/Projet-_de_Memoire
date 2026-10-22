import { useLingui } from '@lingui/react/macro'
import type { PanelsResponse } from '@/shared/api/contracts'

export function StatsBand({ data }: { data: PanelsResponse }) {
  const { t, i18n } = useLingui()
  const geneCount = data.panels.reduce((n, p) => n + p.genes.length, 0)
  const stats = [
    { value: i18n.number(data.variantCount), label: t`variants ClinVar courants` },
    { value: i18n.number(geneCount), label: t`gènes d'intérêt clinique` },
    { value: i18n.number(data.diseaseCount), label: t`maladies (MedGen, OMIM, Orphanet)` },
    { value: i18n.number(data.phenotypeCount), label: t`phénotypes HPO` },
    { value: t`Mensuelle`, label: t`actualisation des sources` },
  ]

  return (
    <section id="donnees" className="scroll-mt-20 border-y border-border bg-card">
      <dl className="mx-auto grid max-w-[1240px] grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-6 px-6 py-9">
        {stats.map((s) => (
          <div key={s.label} className="flex flex-col-reverse gap-1.5">
            <dt className="text-sm text-muted-foreground">{s.label}</dt>
            <dd className="text-[34px] font-semibold tabular-nums tracking-[-0.03em]">{s.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
