import { Trans, useLingui } from '@lingui/react/macro'
import { BarChart3, History, Layers, MessageSquare, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import type { PanelsResponse } from '@/shared/api/contracts'

/** Right half of the auth screens: a short recap of the product, figures read from the backend. */
export function AuthAside({ data }: { data: PanelsResponse }) {
  const { i18n } = useLingui()
  const geneCount = data.panels.reduce((n, p) => n + p.genes.length, 0)
  const variants = i18n.number(data.variantCount)
  const diseases = i18n.number(data.diseaseCount)

  return (
    <aside
      className="relative m-4 hidden min-w-0 flex-[1_1_520px] flex-col justify-center gap-9 overflow-hidden rounded-[32px] px-12 py-14 text-[#f2fbfa] lg:flex"
      style={{
        background:
          'linear-gradient(160deg, color-mix(in oklab, var(--brand-light) 92%, #000), color-mix(in oklab, var(--brand-light) 55%, #020617))',
      }}
    >
      <div className="auth-glow pointer-events-none absolute inset-0" aria-hidden="true" />
      <svg
        aria-hidden="true"
        className="auth-draw absolute -right-36 -top-32 size-[520px] opacity-[0.16]"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={0.3}
        strokeLinecap="round"
      >
        <path pathLength={1} d="M2 15c6.667-6 13.333 0 20-6" />
        <path pathLength={1} d="M9 22c1.798-1.998 2.518-3.995 2.807-5.993" />
        <path pathLength={1} d="M15 2c-1.798 1.998-2.518 3.995-2.807 5.993" />
        <path pathLength={1} d="m17 6-2.5-2.5M14 8l-1-1M7 18l2.5 2.5M3.5 14.5l.5.5M20 9l.5.5M6.5 12.5l1 1M16.5 10.5l1 1M10 16l1.5 1.5" />
      </svg>

      <div className="relative flex max-w-[520px] flex-col gap-3.5">
        <span className="font-mono text-xs uppercase tracking-[0.08em] opacity-75">Genomica</span>
        <h2 className="text-[38px] font-semibold leading-[1.08] tracking-[-0.03em]">
          <Trans>Les variants de l'ADN, expliqués avec leurs sources.</Trans>
        </h2>
        <p className="text-base leading-relaxed opacity-80">
          <Trans>Une base de connaissances actualisée chaque mois à partir de ClinVar, MedGen, HPO et NCBI Gene.</Trans>
        </p>
      </div>

      <ul className="relative grid max-w-[560px] grid-cols-2 gap-3.5">
        <Tile icon={MessageSquare} title={<Trans>Assistant sourcé</Trans>}>
          <Trans>Réponses en français, une fiche ClinVar par affirmation.</Trans>
        </Tile>
        <Tile icon={BarChart3} title={<Trans>Explorateur</Trans>}>
          <Trans>Classifications par gène, niveaux de revue, maladies.</Trans>
        </Tile>
        <Tile icon={History} title={<Trans>Traçabilité</Trans>}>
          <Trans>Archive consultée et historique des reclassifications.</Trans>
        </Tile>
        <Tile
          icon={Layers}
          title={
            <Trans>
              {geneCount} gènes, {data.panels.length} panels
            </Trans>
          }
        >
          <Trans>
            {variants} variants courants, {diseases} maladies associées.
          </Trans>
        </Tile>
      </ul>

      <p className="relative flex items-center gap-2.5 text-[13px] opacity-80">
        <span className="size-2 rounded-full bg-[#5eead4]" aria-hidden="true" />
        <Trans>
          Archive ClinVar <span className="font-mono">{data.archive}</span> · prochaine mise à jour le 10 du mois
        </Trans>
      </p>
    </aside>
  )
}

function Tile({ icon: Icon, title, children }: { icon: LucideIcon; title: ReactNode; children: ReactNode }) {
  return (
    <li className="flex flex-col gap-2.5 rounded-2xl border border-white/12 bg-white/6 p-5 transition-[background-color,transform] duration-200 hover:-translate-y-0.5 hover:bg-white/10">
      <span className="flex size-10 items-center justify-center rounded-[11px] bg-white/12 text-white">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <span className="text-[15px] font-semibold">{title}</span>
      <span className="text-[13px] leading-normal opacity-80">{children}</span>
    </li>
  )
}
