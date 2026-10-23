import { Trans, useLingui } from '@lingui/react/macro'
import { useSuspenseQuery } from '@tanstack/react-query'
import { Check, Inbox, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import type { AccessRequest } from '@/shared/api/contracts'
import { ApiError, errorMessage } from '@/shared/api/errors'
import { Button } from '@/shared/components/ui/button'
import { PROFESSION_LABELS } from '@/features/auth/professions'
import { inputClass } from '@/features/auth/components/FormBits'
import { cn } from '@/lib/utils'
import { accessRequestsQuery, useDecideAccessRequest } from '../hooks'

/** Completed profiles waiting for a decision, oldest first. Each decision is e-mailed and audited. */
export function AccessRequests() {
  const { data: requests } = useSuspenseQuery(accessRequestsQuery)

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-col gap-1.5">
        <h1 className="text-[28px] font-semibold tracking-[-0.03em]">
          <Trans>Demandes d'accès</Trans>
        </h1>
        <p className="text-[15px] text-muted-foreground">
          <Trans>Profils complétés, en attente de votre décision. Le demandeur est prévenu par e-mail.</Trans>
        </p>
      </div>
      {requests.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-border px-6 py-12 text-center text-muted-foreground">
          <Inbox className="size-8" aria-hidden="true" />
          <Trans>Aucune demande en attente.</Trans>
        </div>
      ) : (
        <ul className="flex flex-col gap-4">
          {requests.map((request) => (
            <RequestCard key={request.id} request={request} />
          ))}
        </ul>
      )}
    </section>
  )
}

function RequestCard({ request }: { request: AccessRequest }) {
  const { t, i18n } = useLingui()
  const decide = useDecideAccessRequest()
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const name = request.fullName || request.email

  function submit(decision: 'approve' | 'reject') {
    decide.mutate(
      { id: request.id, decision, reason: decision === 'reject' ? reason : undefined },
      {
        onSuccess: (result) => {
          if (!result.ok) return toast.error(i18n._(errorMessage(new ApiError(result.code, 409))))
          toast.success(decision === 'approve' ? t`Accès accordé à ${name}.` : t`Demande de ${name} refusée.`)
        },
        onError: () => toast.error(i18n._(errorMessage(null))),
      },
    )
  }

  const submittedOn = new Date(request.createdAt).toLocaleDateString(i18n.locale, { dateStyle: 'long' })

  return (
    <li className="flex flex-col gap-4 rounded-2xl border border-border bg-card p-5">
      <div className="flex flex-col gap-1">
        <span className="text-base font-semibold">{name}</span>
        <span className="text-sm text-muted-foreground">{request.email}</span>
      </div>
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[max-content_1fr]">
        <dt className="text-faint">
          <Trans>Fonction</Trans>
        </dt>
        <dd>{request.profession ? i18n._(PROFESSION_LABELS[request.profession]) : '—'}</dd>
        <dt className="text-faint">
          <Trans>Établissement</Trans>
        </dt>
        <dd>{request.organization ?? '—'}</dd>
        <dt className="text-faint">
          <Trans>Usage prévu</Trans>
        </dt>
        <dd className="whitespace-pre-line">{request.intendedUse || '—'}</dd>
        <dt className="text-faint">
          <Trans>Demande du</Trans>
        </dt>
        <dd>{submittedOn}</dd>
      </dl>
      {rejecting ? (
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-2 text-sm font-medium">
            <Trans>Motif du refus (envoyé au demandeur, facultatif)</Trans>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              maxLength={1000}
              className={cn(inputClass, 'h-auto min-h-[72px] py-3 font-normal')}
            />
          </label>
          <div className="flex flex-wrap gap-2.5">
            <Button variant="destructive" disabled={decide.isPending} onClick={() => submit('reject')}>
              <X aria-hidden="true" />
              <Trans>Confirmer le refus</Trans>
            </Button>
            <Button variant="outline" disabled={decide.isPending} onClick={() => setRejecting(false)}>
              <Trans>Annuler</Trans>
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2.5">
          <Button disabled={decide.isPending} onClick={() => submit('approve')}>
            <Check aria-hidden="true" />
            <Trans>Approuver</Trans>
          </Button>
          <Button variant="outline" disabled={decide.isPending} onClick={() => setRejecting(true)}>
            <Trans>Refuser…</Trans>
          </Button>
        </div>
      )}
    </li>
  )
}
