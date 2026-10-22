import { Trans, useLingui } from '@lingui/react/macro'
import { useNavigate, useParams } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'
import { Button } from '@/shared/components/ui/button'
import { LocalizedLink } from '@/shared/components/LocalizedLink'
import { errorMessage, ApiError } from '@/shared/api/errors'
import type { ApiErrorCode } from '@/shared/api/contracts'
import { useSignIn } from '../hooks'
import { safeRedirect } from '../redirect'
import { signInSchema } from '../schemas'
import { AuthTabs, Field, FormAlert, PasswordInput, inputClass } from './FormBits'

/** Statuses that are not errors to fix but a step to wait for: they get their own screen. */
const PENDING: Partial<Record<ApiErrorCode, 'pending_email' | 'pending_review'>> = {
  account_pending_email: 'pending_email',
  account_pending_review: 'pending_review',
}

export function SignInForm({ redirectTo }: { redirectTo?: string }) {
  const { t, i18n } = useLingui()
  const navigate = useNavigate()
  const { lang } = useParams({ from: '/$lang' })
  const signIn = useSignIn()
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({})
  const [formError, setFormError] = useState<string | null>(null)

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    const form = new FormData(event.currentTarget)
    const parsed = signInSchema.safeParse({
      email: String(form.get('email') ?? '').trim(),
      password: String(form.get('password') ?? ''),
      remember: form.get('remember') === 'on',
    })
    if (!parsed.success) {
      const fields = new Set(parsed.error.issues.map((issue) => issue.path[0]))
      setFieldErrors({
        email: fields.has('email') ? t`Saisissez une adresse e-mail valide.` : undefined,
        password: fields.has('password') ? t`Saisissez votre mot de passe.` : undefined,
      })
      return
    }
    setFieldErrors({})
    signIn.mutate(parsed.data, {
      onSuccess: (result) => {
        if (result.ok) return navigate({ href: safeRedirect(redirectTo, `/${lang}/assistant`) })
        const reason = PENDING[result.code]
        if (reason) return navigate({ to: '/$lang/pending', params: { lang }, search: { reason } })
        setFormError(i18n._(errorMessage(new ApiError(result.code, 400))))
      },
      onError: () => setFormError(i18n._(errorMessage(null))),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <AuthTabs current="sign-in" />
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-[18px] animate-in fade-in slide-in-from-bottom-1">
        <div className="flex flex-col gap-2">
          <h1 className="text-[30px] font-semibold tracking-[-0.03em]">
            <Trans>Ravi de vous revoir</Trans>
          </h1>
          <p className="text-[15px] text-muted-foreground">
            <Trans>Connectez-vous pour reprendre vos recherches.</Trans>
          </p>
        </div>
        {formError && <FormAlert>{formError}</FormAlert>}
        <Field label={<Trans>E-mail professionnel</Trans>} error={fieldErrors.email}>
          {(a11y) => (
            <input {...a11y} name="email" type="email" autoComplete="email" placeholder="prenom.nom@chu-exemple.fr" className={inputClass} />
          )}
        </Field>
        <Field
          label={<Trans>Mot de passe</Trans>}
          error={fieldErrors.password}
          aside={
            <LocalizedLink
              to="/forgot-password"
              className="-my-3 inline-flex min-h-11 items-center text-[13px] font-medium text-primary hover:underline"
            >
              <Trans>Mot de passe oublié ?</Trans>
            </LocalizedLink>
          }
        >
          {(a11y) => <PasswordInput {...a11y} name="password" autoComplete="current-password" placeholder={t`Votre mot de passe`} />}
        </Field>
        <label className="flex items-start gap-2.5 text-[13px] leading-normal text-muted-foreground">
          <input type="checkbox" name="remember" className="mt-0.5 size-[18px] accent-primary" />
          <Trans>Rester connecté sur cet appareil (30 jours)</Trans>
        </label>
        <Button type="submit" size="lg" className="h-[46px] text-[15px]" disabled={signIn.isPending}>
          {signIn.isPending ? <Trans>Connexion…</Trans> : <Trans>Se connecter</Trans>}
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          <Trans>
            Pas encore de compte ?{' '}
            <LocalizedLink to="/sign-up" className="text-primary hover:underline">
              Demander un accès
            </LocalizedLink>
          </Trans>
        </p>
      </form>
    </div>
  )
}
