import { Trans } from '@lingui/react/macro'
import { Check, Mail } from 'lucide-react'
import type { ReactNode } from 'react'
import { LocalizedLink } from '@/shared/components/LocalizedLink'
import { buttonVariants } from '@/shared/components/ui/button'
import { cn } from '@/lib/utils'

type StepState = 'done' | 'current' | 'todo'

/**
 * Waiting screen after a sign-up, or after signing in to an account that is not active yet.
 * The steps mirror the account state machine: e-mail check, then admin review.
 */
export function PendingStatus({ reason }: { reason: 'pending_email' | 'pending_review' }) {
  const emailDone = reason === 'pending_review'

  return (
    <div className="flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-1">
      <span className="flex size-14 items-center justify-center rounded-2xl bg-primary/14 text-primary">
        <Mail className="size-7" aria-hidden="true" />
      </span>
      <div className="flex flex-col gap-2">
        <h1 className="text-[30px] font-semibold tracking-[-0.03em]">
          {emailDone ? <Trans>Demande en cours d'examen</Trans> : <Trans>Demande envoyée</Trans>}
        </h1>
        <p className="text-[15px] leading-relaxed text-muted-foreground">
          {emailDone ? (
            <Trans>Votre adresse est confirmée. Vous serez prévenu par e-mail dès que votre accès sera activé.</Trans>
          ) : (
            <Trans>
              Confirmez d'abord votre adresse avec le lien reçu par e-mail. Vous serez prévenu dès que votre accès sera
              activé.
            </Trans>
          )}
        </p>
      </div>
      <ol className="flex flex-col gap-[18px] rounded-2xl border border-border bg-card p-5">
        <Step n={1} state="done" title={<Trans>Demande reçue</Trans>} />
        <Step
          n={2}
          state={emailDone ? 'done' : 'current'}
          title={<Trans>Vérification de l'e-mail</Trans>}
          detail={emailDone ? <Trans>Adresse confirmée</Trans> : <Trans>En attente de votre clic</Trans>}
        />
        <Step
          n={3}
          state={emailDone ? 'current' : 'todo'}
          title={<Trans>Validation par un administrateur</Trans>}
          detail={<Trans>Vous recevrez un e-mail</Trans>}
        />
      </ol>
      <div className="flex flex-wrap gap-2.5">
        <LocalizedLink to="/" className={cn(buttonVariants({ variant: 'outline', size: 'lg' }), 'h-[46px] flex-1')}>
          <Trans>Retour à l'accueil</Trans>
        </LocalizedLink>
        <LocalizedLink to="/sign-in" className={cn(buttonVariants({ variant: 'outline', size: 'lg' }), 'h-[46px] flex-1')}>
          <Trans>Se connecter</Trans>
        </LocalizedLink>
      </div>
    </div>
  )
}

function Step({ n, state, title, detail }: { n: number; state: StepState; title: ReactNode; detail?: ReactNode }) {
  return (
    <li className="flex items-start gap-3.5" aria-current={state === 'current' ? 'step' : undefined}>
      <span
        className={cn(
          'flex size-7 shrink-0 items-center justify-center rounded-full font-mono text-xs font-semibold',
          state === 'done' && 'bg-success text-white',
          state === 'current' && 'border-2 border-primary text-primary',
          state === 'todo' && 'border-2 border-border text-faint',
        )}
        aria-hidden="true"
      >
        {state === 'done' ? <Check className="size-3.5" strokeWidth={3} /> : n}
      </span>
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium">{title}</span>
        {detail && <span className="text-[13px] text-muted-foreground">{detail}</span>}
      </div>
    </li>
  )
}
