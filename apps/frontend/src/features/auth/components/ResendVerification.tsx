import { Trans, useLingui } from '@lingui/react/macro'
import { useState, type FormEvent } from 'react'
import { Button } from '@/shared/components/ui/button'
import { ApiError, errorMessage } from '@/shared/api/errors'
import { useResendVerification } from '../hooks'
import { emailSchema } from '../schemas'
import { Field, inputClass } from './FormBits'

/** Asks for a fresh verification link; the answer is the same whether the address is known or not. */
export function ResendVerification() {
  const { t, i18n } = useLingui()
  const resend = useResendVerification()
  const [error, setError] = useState<string>()

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsed = emailSchema.safeParse({ email: String(new FormData(event.currentTarget).get('email') ?? '').trim() })
    if (!parsed.success) return setError(t`Saisissez une adresse e-mail valide.`)
    setError(undefined)
    resend.mutate(parsed.data.email, {
      onSuccess: (result) => {
        if (!result.ok) setError(i18n._(errorMessage(new ApiError(result.code, 429))))
      },
    })
  }

  if (resend.data?.ok) {
    return (
      <p role="status" className="rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
        <Trans>Si une demande est en attente pour cette adresse, un nouveau lien vient d'être envoyé.</Trans>
      </p>
    )
  }

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-3 rounded-2xl border border-border bg-card p-5">
      <Field label={<Trans>Pas reçu l'e-mail ? Recevoir un nouveau lien</Trans>} error={error}>
        {(a11y) => (
          <input
            {...a11y}
            name="email"
            type="email"
            autoComplete="email"
            placeholder="prenom.nom@chu-exemple.fr"
            className={inputClass}
          />
        )}
      </Field>
      <Button type="submit" variant="outline" size="lg" className="h-[46px]" disabled={resend.isPending}>
        <Trans>Renvoyer le lien</Trans>
      </Button>
    </form>
  )
}
