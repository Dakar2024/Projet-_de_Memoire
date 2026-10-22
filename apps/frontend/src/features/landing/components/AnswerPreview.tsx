import { Trans, useLingui } from '@lingui/react/macro'
import { Search } from 'lucide-react'
import type { CSSProperties } from 'react'
import { LogoMark } from '@/shared/components/brand/LogoMark'
import { LocalizedLink } from '@/shared/components/LocalizedLink'
import { SectionHeading } from './SectionHeading'

/**
 * Product preview with a real ClinVar example: rs334 maps to two HBB alleles with opposite classifications.
 * Data read from the RAG index (archive 2026-10); the animation plays once on load.
 */
export function AnswerPreview({ archive }: { archive: string }) {
  const { t } = useLingui()
  const question = t`Le variant rs334 de HBB est-il pathogène ?`
  const examples = [
    t`rs334 sur HBB est-il pathogène ?`,
    t`Classification de BRCA1 c.68_69del ?`,
    t`TP53 p.Arg175His a-t-il été reclassé ?`,
    t`Maladies associées à PALB2 ?`,
    t`Statut de revue de BRCA1 c.5123C>A ?`,
  ]

  return (
    <section id="apercu" className="mx-auto flex max-w-[1240px] scroll-mt-20 flex-col items-center gap-10 px-6 pb-10 pt-28">
      <SectionHeading
        centered
        eyebrow={<Trans>Aperçu</Trans>}
        title={<Trans>Une question, une réponse, ses preuves.</Trans>}
        lead={
          <Trans>
            Un identifiant dbSNP peut désigner plusieurs allèles. Genomica les distingue et cite la fiche ClinVar de
            chacun.
          </Trans>
        }
      />

      <figure className="w-full max-w-[920px] overflow-hidden rounded-[18px] border border-border bg-card shadow-elevated">
        <div className="flex items-center gap-2 border-b border-border bg-muted px-4 py-3" aria-hidden="true">
          <span className="size-2.5 rounded-full bg-border" />
          <span className="size-2.5 rounded-full bg-border" />
          <span className="size-2.5 rounded-full bg-border" />
          <span className="ml-3 font-mono text-xs text-faint">genomica · assistant</span>
        </div>
        <div className="flex flex-col gap-6 p-8">
          <p className="self-end rounded-2xl bg-muted px-4 py-3 text-[15px]">
            <span className="typing font-mono" style={{ '--chars': question.length } as CSSProperties}>
              {question}
            </span>
          </p>
          <div className="flex items-start gap-3.5">
            <LogoMark size={32} className="reveal [animation-delay:3.4s]" />
            <div className="flex min-w-0 flex-col gap-4">
              <p className="reveal text-base leading-[1.65] [animation-delay:3.6s]">
                <Trans>
                  L'identifiant rs334 correspond à deux allèles distincts dans ClinVar. Le variant{' '}
                  <span className="font-mono">HBB c.20A&gt;T (p.Glu7Val)</span>, responsable de l'hémoglobine S, est
                  classé <strong className="text-sig-p-text">pathogène</strong> [1]. L'allèle{' '}
                  <span className="font-mono">c.20A&gt;C (p.Glu7Ala)</span> est classé{' '}
                  <strong className="text-sig-lb-text">probablement bénin</strong> [2].
                </Trans>
              </p>
              <div className="reveal grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-3 [animation-delay:4.2s]">
                <PreviewSource n={1} vcv="15333" hgvs="HBB c.20A>T · p.Glu7Val" stars={2} tone="p" label={t`Pathogène`} />
                <PreviewSource n={2} vcv="15175" hgvs="HBB c.20A>C · p.Glu7Ala" stars={1} tone="lb" label={t`Probablement bénin`} />
              </div>
              <figcaption className="reveal text-xs text-faint [animation-delay:4.8s]">
                <Trans>
                  Aide à la consultation de ClinVar (archive {archive}) ; ne remplace pas l'interprétation clinique d'un
                  biologiste.
                </Trans>
              </figcaption>
            </div>
          </div>
        </div>
      </figure>

      <ul className="flex max-w-[920px] flex-wrap justify-center gap-2.5" aria-label={t`Exemples de questions`}>
        {examples.map((q) => (
          <li key={q}>
            <LocalizedLink
              to="/sign-up"
              className="inline-flex min-h-10 items-center gap-2 rounded-full border border-border bg-card px-3.5 text-sm transition-colors hover:border-primary hover:bg-primary/5"
            >
              <Search className="size-3.5 text-primary" aria-hidden="true" />
              {q}
            </LocalizedLink>
          </li>
        ))}
      </ul>
    </section>
  )
}

function PreviewSource(props: { n: number; vcv: string; hgvs: string; stars: number; tone: 'p' | 'lb'; label: string }) {
  const { t } = useLingui()
  const color = props.tone === 'p' ? 'text-sig-p-text bg-sig-p/12' : 'text-sig-lb-text bg-sig-lb/15'
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border p-3.5">
      <div className="flex justify-between gap-2 text-xs text-muted-foreground">
        <span>
          [{props.n}] ClinVar · VCV {props.vcv}
        </span>
        <span className="text-primary">{props.stars === 1 ? t`1 étoile` : t`${props.stars} étoiles`}</span>
      </div>
      <span className="font-mono text-[13px]">{props.hgvs}</span>
      <span className={`self-start rounded-md px-2 py-1 text-xs font-medium ${color}`}>{props.label}</span>
    </div>
  )
}
