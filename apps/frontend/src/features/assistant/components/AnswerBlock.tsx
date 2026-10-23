import { Trans, useLingui } from '@lingui/react/macro'
import { msg } from '@lingui/core/macro'
import type { MessageDescriptor } from '@lingui/core'
import { Ban, Check, CircleAlert, Copy, History, SearchX, ShieldAlert, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import type { AnswerStatus, AssistantMessage, ScopeReason } from '@/shared/api/contracts'
import { cn } from '@/lib/utils'
import { SourceCard } from './SourceCard'

type Notice = { icon: LucideIcon; title: MessageDescriptor; tone: 'warning' | 'neutral' }

/** Every status except `answered` gets a notice above the text, so a partial answer never reads as complete. */
const NOTICES: Partial<Record<AnswerStatus, Notice>> = {
  partial: {
    icon: CircleAlert,
    title: msg`Réponse partielle : les fiches retrouvées ne couvrent qu'une partie de la question.`,
    tone: 'warning',
  },
  not_in_sources: { icon: SearchX, title: msg`Aucune fiche correspondante dans les sources.`, tone: 'neutral' },
  out_of_scope: { icon: Ban, title: msg`Question hors du périmètre de l'outil.`, tone: 'neutral' },
  unverifiable: {
    icon: ShieldAlert,
    title: msg`Réponse non vérifiable : seules les fiches retrouvées sont affichées.`,
    tone: 'warning',
  },
}

const SCOPE_LABELS: Record<ScopeReason, MessageDescriptor> = {
  counting: msg`Comptage ou liste exhaustive`,
  acmg: msg`Classification ACMG`,
  frequency: msg`Fréquence en population`,
  clinical_advice: msg`Conseil clinique`,
  other: msg`Autre sujet`,
  gene_out_of_panel: msg`Gène hors panel`,
}

export function AnswerBlock({ message }: { message: AssistantMessage }) {
  const { t, i18n } = useLingui()
  const notice = NOTICES[message.status]

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-4">
      {notice && (
        <div
          className={cn(
            'flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-sm',
            notice.tone === 'warning'
              ? 'border-warning/30 bg-warning/8 text-foreground'
              : 'border-border bg-muted text-muted-foreground',
          )}
        >
          <notice.icon
            className={cn('mt-0.5 size-4 shrink-0', notice.tone === 'warning' ? 'text-warning' : '')}
            aria-hidden="true"
          />
          <span>
            {i18n._(notice.title)}
            {message.scopeReason && (
              <span className="ml-1.5 rounded-md bg-background px-1.5 py-0.5 text-xs">
                {i18n._(SCOPE_LABELS[message.scopeReason])}
              </span>
            )}
          </span>
        </div>
      )}

      <p className="whitespace-pre-line text-[15px] leading-[1.7]">{message.content}</p>

      {message.history.length > 0 && (
        <ul className="flex flex-col gap-1.5 text-sm text-muted-foreground">
          {message.history.map((line) => (
            <li key={line} className="flex items-start gap-2">
              <History className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              {line}
            </li>
          ))}
        </ul>
      )}

      {message.sources.length > 0 && (
        <section className="flex flex-col gap-2.5" aria-label={t`Sources citées`}>
          <h3 className="text-xs font-medium uppercase tracking-[0.06em] text-muted-foreground">
            <Trans>Sources ({message.sources.length})</Trans>
          </h3>
          <ol className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-2.5">
            {message.sources.map((source) => (
              <SourceCard key={source.rank} source={source} />
            ))}
          </ol>
        </section>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="min-w-0 flex-1 text-xs leading-normal text-faint">{message.disclaimer}</p>
        <CopyButton text={message.content} />
      </div>
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const { t } = useLingui()
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1600)
      }}
      className="inline-flex size-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      aria-label={copied ? t`Réponse copiée` : t`Copier la réponse`}
    >
      {copied ? <Check className="size-4 text-success" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}
    </button>
  )
}
