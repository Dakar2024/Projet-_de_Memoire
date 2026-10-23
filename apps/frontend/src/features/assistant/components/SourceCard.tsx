import { useLingui } from '@lingui/react/macro'
import { ArrowUpRight, Star } from 'lucide-react'
import type { AnswerSource } from '@/shared/api/contracts'
import { cn } from '@/lib/utils'
import { significanceTone, type SignificanceTone } from '../significance'

const DOT: Record<SignificanceTone, string> = {
  p: 'bg-sig-p',
  lp: 'bg-sig-lp',
  vus: 'bg-sig-vus',
  lb: 'bg-sig-lb',
  b: 'bg-sig-b',
  conf: 'bg-sig-conf',
  other: 'bg-faint',
}

/**
 * Clinical significance as a colored dot plus the French label: the color helps scanning,
 * the text carries the meaning, so the chip stays readable without color vision.
 */
export function SignificanceChip({ significance, label }: { significance: string | null; label: string | null }) {
  const tone = significanceTone(significance)
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs font-medium">
      <span className={cn('size-2 shrink-0 rounded-full', DOT[tone])} aria-hidden="true" />
      {label ?? significance ?? '—'}
    </span>
  )
}

/** ClinVar review level as 0 to 4 stars; the review status text stays available to screen readers. */
function ReviewStars({ stars, reviewStatus }: { stars: number; reviewStatus: string | null }) {
  const { t } = useLingui()
  const label = stars === 1 ? t`1 étoile sur 4` : t`${stars} étoiles sur 4`
  return (
    <span className="inline-flex items-center gap-0.5 text-primary" title={reviewStatus ?? undefined}>
      <span className="sr-only">
        {label}
        {reviewStatus ? ` (${reviewStatus})` : ''}
      </span>
      {Array.from({ length: 4 }, (_, i) => (
        <Star
          key={i}
          className={cn('size-3', i < stars ? 'fill-current' : 'opacity-30')}
          aria-hidden="true"
        />
      ))}
    </span>
  )
}

export function SourceCard({ source }: { source: AnswerSource }) {
  const { t } = useLingui()
  return (
    <li className="flex min-w-0 flex-col gap-2.5 rounded-xl border border-border bg-card p-3.5">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          [{source.rank}] ClinVar{source.clinvarVariationId ? ` · VCV ${source.clinvarVariationId}` : ''}
        </span>
        {source.stars !== null && <ReviewStars stars={source.stars} reviewStatus={source.reviewStatus} />}
      </div>
      <p className="min-w-0 break-words font-mono text-[13px] leading-snug">
        <span className="font-semibold">{source.gene}</span> {source.variant}
        {source.protein ? <span className="text-muted-foreground"> · {source.protein}</span> : null}
      </p>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SignificanceChip significance={source.significance} label={source.significanceFr} />
        {source.clinvarUrl && (
          <a
            href={source.clinvarUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-8 items-center gap-1 rounded-md text-xs font-medium text-primary hover:underline"
            aria-label={t`Ouvrir la fiche ClinVar ${source.clinvarVariationId ?? ''} dans un nouvel onglet`}
          >
            ClinVar
            <ArrowUpRight className="size-3.5" aria-hidden="true" />
          </a>
        )}
      </div>
    </li>
  )
}
