import { Trans, useLingui } from '@lingui/react/macro'
import { useState, type FormEvent } from 'react'
import { Button } from '@/shared/components/ui/button'
import { LocalizedLink } from '@/shared/components/LocalizedLink'
import { useForgotPassword } from '../hooks'
import { emailSchema } from '../schemas'
import { Field, inputClass } from './FormBits'

export function ForgotPasswordForm() {
  const { t } = useLingui()
  const forgot = useForgotPassword()
  const [error, setError] = useState<string>()

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const parsed = emailSchema.safeParse({ email: String(new FormData(event.currentTarget).get('email') ?? '').trim() })
    if (!parsed.success) return setError(t`Saisissez une adresse e-mail valide.`)
    setError(undefined)
    forgot.mutate(parsed.data.email)
  }

  if (forgot.isSuccess) {
    return (
      <div className="flex flex-col gap-4 animate-in fade-in" role="status">
        <h1 className="text-[30px] font-semibold tracking-[-0.03em]">
          <Trans>Vérifiez votre messagerie</Trans>
        </h1>
        <p className="text-[15px] leading-relaxed text-muted-foreground">
          <Trans>Si un compte existe pour cette adresse, un lien de réinitialisation vient d'être envoyé.</Trans>
        </p>
        <LocalizedLink to="/sign-in" className="text-sm text-primary hover:underline">
          <Trans>Retour à la connexion</Trans>
        </LocalizedLink>
      </div>
    )
  }

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-[18px]">
      <div className="flex flex-col gap-2">
        <h1 className="text-[30px] font-semibold tracking-[-0.03em]">
          <Trans>Mot de passe oublié</Trans>
        </h1>
        <p className="text-[15px] text-muted-foreground">
          <Trans>Indiquez votre e-mail : nous vous enverrons un lien pour en choisir un nouveau.</Trans>
        </p>
      </div>
      <Field label={<Trans>E-mail professionnel</Trans>} error={error}>
        {(a11y) => <input {...a11y} name="email" type="email" autoComplete="email" className={inputClass} />}
      </Field>
      <Button type="submit" size="lg" className="h-[46px] text-[15px]" disabled={forgot.isPending}>
        <Trans>Envoyer le lien</Trans>
      </Button>
      <LocalizedLink to="/sign-in" className="text-center text-sm text-primary hover:underline">
        <Trans>Retour à la connexion</Trans>
      </LocalizedLink>
    </form>
  )
}
