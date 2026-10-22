import { Trans, useLingui } from '@lingui/react/macro'
import { BookOpen, MessageSquare, ShieldCheck, type LucideIcon } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import type { PanelsResponse } from '@/shared/api/contracts'
import { cn } from '@/lib/utils'

/** Sine strand of a helix rising from the bottom of a 500×700 box, sampled every 8 px. */
function strand(amplitude: number, phase: number, top: number): string {
  const points: string[] = []
  for (let y = 700; y >= top; y -= 8) {
    const x = 250 + amplitude * Math.sin((y / 700) * Math.PI * 3 + phase)
    points.push(`${x.toFixed(1)} ${y}`)
  }
  return `M${points.join(' L')}`
}

const STRANDS = [
  { d: strand(150, 0, 150), opacity: 0.9 },
  { d: strand(150, Math.PI, 150), opacity: 0.55 },
  { d: strand(205, 0.6, 230), opacity: 0.22 },
  { d: strand(205, Math.PI + 0.6, 230), opacity: 0.14 },
]

/** Rungs where the two inner strands are furthest apart. */
const RUNGS = Array.from({ length: 6 }, (_, i) => {
  const y = 700 - ((i + 0.5) * 700) / 6
  const dx = Math.abs(150 * Math.sin((y / 700) * Math.PI * 3))
  return { y, x1: 250 - dx + 14, x2: 250 + dx - 14 }
}).filter((r) => r.x2 - r.x1 > 60 && r.y > 170)

type Step = { icon: LucideIcon; title: ReactNode; text: ReactNode; tone: 'light' | 'dark'; indent: string; delay: string }

/**
 * Illustrated side of the auth screens: a helix drawing itself above three stacked cards that tell the
 * product in three steps. The drawing is decorative; the cards stay readable by screen readers.
 */
export function AuthArt({ data }: { data: PanelsResponse }) {
  const { t, i18n } = useLingui()
  const geneCount = data.panels.reduce((n, p) => n + p.genes.length, 0)
  const steps: Step[] = [
    {
      icon: MessageSquare,
      title: <Trans>Une question posée</Trans>,
      text: <Trans>Identifiant rs, notation HGVS ou phrase libre</Trans>,
      tone: 'light',
      indent: '',
      delay: '0.6s',
    },
    {
      icon: BookOpen,
      title: <Trans>Des fiches retrouvées</Trans>,
      text: <Trans>ClinVar, MedGen, HPO et NCBI Gene</Trans>,
      tone: 'light',
      indent: 'ml-6',
      delay: '0.75s',
    },
    {
      icon: ShieldCheck,
      title: <Trans>Une réponse sourcée</Trans>,
      text: <Trans>Chaque affirmation reliée à sa fiche</Trans>,
      tone: 'dark',
      indent: 'ml-12',
      delay: '0.9s',
    },
  ]

  return (
    <section
      className="relative m-4 flex min-h-[360px] min-w-0 flex-[1_1_520px] items-end justify-center overflow-hidden rounded-[40px] bg-[color-mix(in_oklab,var(--primary)_14%,var(--card))] lg:min-h-[600px]"
      aria-label={t`Genomica en trois étapes`}
    >
      <div className="auth-glow pointer-events-none absolute inset-0" aria-hidden="true" />
      <svg
        viewBox="0 0 500 700"
        preserveAspectRatio="xMidYMax meet"
        className="auth-draw pointer-events-none absolute inset-0 size-full text-primary"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        aria-hidden="true"
      >
        {STRANDS.map((s) => (
          <path key={s.d} d={s.d} pathLength={1} strokeWidth={3} style={{ opacity: s.opacity }} />
        ))}
        {RUNGS.map((r) => (
          <line
            key={r.y}
            x1={r.x1}
            x2={r.x2}
            y1={r.y}
            y2={r.y}
            strokeWidth={3}
            className="auth-rung"
            style={{ opacity: 0.35 }}
          />
        ))}
      </svg>

      <p className="absolute left-7 top-6 font-mono text-xs text-muted-foreground">
        <Trans>
          {i18n.number(data.variantCount)} variants · {geneCount} gènes · archive {data.archive}
        </Trans>
      </p>

      <ol className="relative z-10 mb-10 flex w-full max-w-[380px] flex-col gap-3 px-6">
        {steps.map(({ icon: Icon, title, text, tone, indent, delay }, i) => (
          <li
            key={i}
            className={cn(
              'flex items-center gap-3.5 rounded-2xl p-3.5 shadow-elevated animate-in fade-in slide-in-from-bottom-3 fill-mode-backwards duration-700',
              tone === 'dark' ? 'bg-foreground text-background' : 'bg-card text-foreground',
              indent,
            )}
            style={{ animationDelay: delay } as CSSProperties}
          >
            <span
              className={cn(
                'flex size-10 shrink-0 items-center justify-center rounded-xl',
                tone === 'dark' ? 'bg-primary text-primary-foreground' : 'bg-primary/12 text-primary',
              )}
              aria-hidden="true"
            >
              <Icon className="size-5" />
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="text-[15px] font-semibold">{title}</span>
              <span className={cn('text-[13px]', tone === 'dark' ? 'opacity-70' : 'text-muted-foreground')}>{text}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  )
}
