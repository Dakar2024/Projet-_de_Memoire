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
import { AuthHeading, AuthTabs, Field, FormAlert, PasswordInput, inputClass } from './FormBits'
import { SsoBlock } from './SsoBlock'

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
  const next = safeRedirect(redirectTo, `/${lang}/assistant`)

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    const form = new FormData(event.currentTarget)
    const parsed = signInSchema.safeParse({
      email: String(form.get('email') ?? '').trim(),
      password: String(form.get('password') ?? ''),
      remember: false,
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
        if (result.ok) return navigate({ href: next })
        const reason = PENDING[result.code]
        if (reason) return navigate({ to: '/$lang/pending', params: { lang }, search: { reason } })
        setFormError(i18n._(errorMessage(new ApiError(result.code, 400))))
      },
      onError: () => setFormError(i18n._(errorMessage(null))),
    })
  }

  return (
    <div className="flex flex-col gap-8 animate-in fade-in slide-in-from-bottom-1">
      <AuthHeading
        title={<Trans>Ravi de vous revoir</Trans>}
        lead={<Trans>Connectez-vous pour reprendre vos recherches.</Trans>}
      />
      <AuthTabs current="sign-in" />
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-5">
        <SsoBlock next={next} />
        {formError && <FormAlert>{formError}</FormAlert>}
        <Field label={<Trans>E-mail professionnel</Trans>} error={fieldErrors.email}>
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
        <Field label={<Trans>Mot de passe</Trans>} error={fieldErrors.password}>
          {(a11y) => (
            <PasswordInput {...a11y} name="password" autoComplete="current-password" placeholder={t`Votre mot de passe`} />
          )}
        </Field>
        <LocalizedLink
          to="/forgot-password"
          className="-my-3 inline-flex min-h-11 items-center self-end text-sm font-semibold text-foreground underline underline-offset-4 hover:text-primary"
        >
          <Trans>Mot de passe oublié ?</Trans>
        </LocalizedLink>
        <Button type="submit" size="lg" className="h-[54px] w-full rounded-xl text-base font-semibold" disabled={signIn.isPending}>
          {signIn.isPending ? <Trans>Connexion…</Trans> : <Trans>Se connecter</Trans>}
        </Button>
      </form>
    </div>
  )
}
