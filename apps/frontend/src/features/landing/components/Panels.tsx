import { Trans, useLingui } from '@lingui/react/macro'
import type { PanelsResponse } from '@/shared/api/contracts'
import { PANEL_LABELS } from '../panels'
import { SectionHeading } from './SectionHeading'

/** One card per panel, read from the backend: adding a panel to the pipeline adds a card with no code change. */
export function Panels({ data }: { data: PanelsResponse }) {
  const { i18n } = useLingui()

  return (
    <section aria-labelledby="panels-title" className="mx-auto flex max-w-[1240px] flex-col gap-10 px-6 py-24">
      <SectionHeading
        id="panels-title"
        eyebrow={<Trans>Couverture</Trans>}
        title={<Trans>Des panels de gènes cliniques, extensibles.</Trans>}
        lead={<Trans>Ajouter une pathologie revient à déclarer un nouveau panel : la chaîne de traitement est la même.</Trans>}
      />
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,340px),1fr))] gap-4">
        {data.panels.map((panel) => (
          <article key={panel.id} className="flex flex-col gap-4 rounded-[18px] border border-border bg-card p-7">
            <div className="flex items-baseline justify-between gap-3">
              <h3 className="text-xl font-semibold">{i18n._(PANEL_LABELS[panel.id])}</h3>
              <span className="font-mono text-[13px] text-muted-foreground">
                <Trans>{i18n.number(panel.variantCount)} variants</Trans>
              </span>
            </div>
            <ul className="flex flex-wrap gap-2">
              {panel.genes.map((gene) => (
                <li
                  key={gene}
                  className="rounded-lg border border-border bg-muted px-2.5 py-1.5 font-mono text-xs font-medium transition-colors hover:border-primary hover:text-primary"
                >
                  {gene}
                </li>
              ))}
            </ul>
          </article>
        ))}
        <div className="flex flex-col justify-center gap-2.5 rounded-[18px] border-[1.5px] border-dashed border-border p-7">
          <h3 className="text-lg font-semibold">
            <Trans>D'autres panels à venir</Trans>
          </h3>
          <p className="text-[15px] leading-relaxed text-muted-foreground">
            <Trans>Vous suivez une pathologie précise ? Indiquez-la lors de votre demande d'accès.</Trans>
          </p>
        </div>
      </div>
    </section>
  )
}
