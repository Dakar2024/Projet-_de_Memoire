import { Trans, useLingui } from '@lingui/react/macro'
import { useNavigate, useParams } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'
import { Button } from '@/shared/components/ui/button'
import { ApiError, errorMessage } from '@/shared/api/errors'
import { useSignUp } from '../hooks'
import { PASSWORD_MIN_LENGTH, signUpFormSchema } from '../schemas'
import { AuthHeading, AuthTabs, Field, FormAlert, PasswordInput, PasswordStrength, inputClass } from './FormBits'
import { SsoBlock } from './SsoBlock'

type FieldName = 'email' | 'password' | 'passwordConfirm' | 'consent'

/**
 * Access request kept to the essentials: professional e-mail, password, confirmation and one consent.
 * Name, profession and organisation are asked after the e-mail is verified (onboarding).
 */
export function SignUpForm() {
  const { t, i18n } = useLingui()
  const navigate = useNavigate()
  const { lang } = useParams({ from: '/$lang' })
  const signUp = useSignUp()
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<Partial<Record<FieldName, string>>>({})
  const [formError, setFormError] = useState<string | null>(null)

  function emailError(code: string | undefined) {
    return code === 'not_professional'
      ? t`Utilisez l'adresse de votre établissement ou laboratoire, pas une messagerie personnelle.`
      : t`Saisissez une adresse e-mail valide.`
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    const form = new FormData(event.currentTarget)
    const consent = form.get('consent') === 'on'
    const parsed = signUpFormSchema.safeParse({
      email: String(form.get('email') ?? '').trim(),
      password: String(form.get('password') ?? ''),
      passwordConfirm: String(form.get('passwordConfirm') ?? ''),
      termsAccepted: consent,
      noPatientDataPledge: consent,
    })
    if (!parsed.success) {
      const next: Partial<Record<FieldName, string>> = {}
      for (const issue of parsed.error.issues) {
        const name = String(issue.path[0])
        if (name === 'email') next.email = emailError(issue.message)
        else if (name === 'password') next.password = t`${PASSWORD_MIN_LENGTH} caractères minimum.`
        else if (name === 'passwordConfirm') next.passwordConfirm = t`Les mots de passe ne correspondent pas.`
        else next.consent = t`Vous devez accepter ces conditions pour continuer.`
      }
      setErrors(next)
      return
    }
    setErrors({})
    const { passwordConfirm: _confirm, ...request } = parsed.data
    signUp.mutate(request, {
      onSuccess: (result) => {
        if (result.ok) return navigate({ to: '/$lang/pending', params: { lang }, search: { reason: 'pending_email' } })
        setFormError(i18n._(errorMessage(new ApiError(result.code, 400))))
      },
      onError: () => setFormError(i18n._(errorMessage(null))),
    })
  }

  return (
    <div className="flex flex-col gap-8 animate-in fade-in slide-in-from-bottom-1">
      <AuthHeading
        title={<Trans>Demander un accès</Trans>}
        lead={<Trans>Inscrivez-vous avec votre e-mail professionnel ; un administrateur validera votre accès.</Trans>}
      />
      <AuthTabs current="sign-up" />
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-5">
        <SsoBlock />
        {formError && <FormAlert>{formError}</FormAlert>}
        <Field
          label={<Trans>E-mail professionnel</Trans>}
          error={errors.email}
          hint={<Trans>Adresse de votre établissement ou laboratoire. Un lien de vérification vous sera envoyé.</Trans>}
        >
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
        <Field label={<Trans>Mot de passe</Trans>} error={errors.password}>
          {(a11y) => (
            <div className="flex flex-col gap-2.5">
              <PasswordInput
                {...a11y}
                name="password"
                autoComplete="new-password"
                placeholder={t`${PASSWORD_MIN_LENGTH} caractères minimum`}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <PasswordStrength password={password} />
            </div>
          )}
        </Field>
        <Field label={<Trans>Confirmer le mot de passe</Trans>} error={errors.passwordConfirm}>
          {(a11y) => <PasswordInput {...a11y} name="passwordConfirm" autoComplete="new-password" />}
        </Field>
        <div className="flex flex-col gap-1">
          <label className="flex items-start gap-3 text-sm leading-normal text-muted-foreground">
            <input
              type="checkbox"
              name="consent"
              aria-invalid={Boolean(errors.consent)}
              className="mt-0.5 size-[18px] shrink-0 accent-primary"
            />
            <span>
              <Trans>
                J'accepte les{' '}
                <a href="#" target="_blank" className="text-foreground underline underline-offset-4">
                  conditions d'utilisation
                </a>{' '}
                et la{' '}
                <a href="#" target="_blank" className="text-foreground underline underline-offset-4">
                  politique de confidentialité
                </a>
                , et je m'engage à ne saisir aucune donnée permettant d'identifier un patient.
              </Trans>
            </span>
          </label>
          {errors.consent && (
            <span role="alert" className="pl-[30px] text-xs text-destructive">
              {errors.consent}
            </span>
          )}
        </div>
        <Button type="submit" size="lg" className="h-[54px] w-full rounded-xl text-base font-semibold" disabled={signUp.isPending}>
          {signUp.isPending ? <Trans>Envoi…</Trans> : <Trans>Envoyer ma demande</Trans>}
        </Button>
      </form>
    </div>
  )
}
