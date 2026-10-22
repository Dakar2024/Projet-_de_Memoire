import { Trans, useLingui } from '@lingui/react/macro'
import { useNavigate, useParams } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'
import { Button } from '@/shared/components/ui/button'
import { LocalizedLink } from '@/shared/components/LocalizedLink'
import { PROFESSIONS } from '@/shared/api/contracts'
import { ApiError, errorMessage } from '@/shared/api/errors'
import { useSignUp } from '../hooks'
import { PASSWORD_MIN_LENGTH, signUpSchema } from '../schemas'
import { PROFESSION_LABELS } from '../professions'
import { AuthTabs, Field, FormAlert, PasswordInput, PasswordStrength, inputClass } from './FormBits'

type FieldName =
  | 'firstName'
  | 'lastName'
  | 'email'
  | 'organization'
  | 'password'
  | 'noPatientDataPledge'
  | 'termsAccepted'

export function SignUpForm() {
  const { t, i18n } = useLingui()
  const navigate = useNavigate()
  const { lang } = useParams({ from: '/$lang' })
  const signUp = useSignUp()
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<Partial<Record<FieldName, string>>>({})
  const [formError, setFormError] = useState<string | null>(null)

  const messages: Record<FieldName, string> = {
    firstName: t`Indiquez votre prénom.`,
    lastName: t`Indiquez votre nom.`,
    email: t`Saisissez une adresse e-mail valide.`,
    organization: t`Indiquez votre établissement.`,
    password: t`${PASSWORD_MIN_LENGTH} caractères minimum.`,
    noPatientDataPledge: t`Cet engagement est obligatoire.`,
    termsAccepted: t`Vous devez accepter les conditions pour continuer.`,
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    const form = new FormData(event.currentTarget)
    const text = (name: string) => String(form.get(name) ?? '').trim()
    const parsed = signUpSchema.safeParse({
      firstName: text('firstName'),
      lastName: text('lastName'),
      email: text('email'),
      profession: text('profession'),
      organization: text('organization'),
      password: String(form.get('password') ?? ''),
      intendedUse: text('intendedUse') || undefined,
      noPatientDataPledge: form.get('noPatientDataPledge') === 'on',
      termsAccepted: form.get('termsAccepted') === 'on',
    })
    if (!parsed.success) {
      const next: Partial<Record<FieldName, string>> = {}
      for (const issue of parsed.error.issues) {
        const name = issue.path[0] as FieldName
        if (name in messages) next[name] = messages[name]
      }
      setErrors(next)
      return
    }
    setErrors({})
    signUp.mutate(parsed.data, {
      onSuccess: (result) => {
        if (result.ok) return navigate({ to: '/$lang/pending', params: { lang }, search: { reason: 'pending_email' } })
        setFormError(i18n._(errorMessage(new ApiError(result.code, 400))))
      },
      onError: () => setFormError(i18n._(errorMessage(null))),
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <AuthTabs current="sign-up" />
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4 animate-in fade-in slide-in-from-bottom-1">
        <div className="flex flex-col gap-2">
          <h1 className="text-[30px] font-semibold tracking-[-0.03em]">
            <Trans>Demander un accès</Trans>
          </h1>
          <p className="text-[15px] leading-normal text-muted-foreground">
            <Trans>Genomica est réservé aux professionnels. Votre demande sera examinée par un administrateur.</Trans>
          </p>
        </div>
        {formError && <FormAlert>{formError}</FormAlert>}
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
          <Field label={<Trans>Prénom</Trans>} error={errors.firstName}>
            {(a11y) => <input {...a11y} name="firstName" autoComplete="given-name" className={inputClass} />}
          </Field>
          <Field label={<Trans>Nom</Trans>} error={errors.lastName}>
            {(a11y) => <input {...a11y} name="lastName" autoComplete="family-name" className={inputClass} />}
          </Field>
        </div>
        <Field
          label={<Trans>E-mail professionnel</Trans>}
          error={errors.email}
          hint={<Trans>Un lien de vérification vous sera envoyé.</Trans>}
        >
          {(a11y) => (
            <input {...a11y} name="email" type="email" autoComplete="email" placeholder="prenom.nom@etablissement.fr" className={inputClass} />
          )}
        </Field>
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
          <Field label={<Trans>Fonction</Trans>}>
            {(a11y) => (
              <select {...a11y} name="profession" defaultValue="medical_biologist" className={inputClass}>
                {PROFESSIONS.map((p) => (
                  <option key={p} value={p}>
                    {i18n._(PROFESSION_LABELS[p])}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={<Trans>Établissement</Trans>} error={errors.organization}>
            {(a11y) => (
              <input {...a11y} name="organization" autoComplete="organization" placeholder={t`CHU, laboratoire…`} className={inputClass} />
            )}
          </Field>
        </div>
        <Field label={<Trans>Mot de passe</Trans>} error={errors.password}>
          {(a11y) => (
            <div className="flex flex-col gap-2">
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
        <Field
          label={
            <Trans>
              Usage prévu <span className="font-normal text-faint">(facultatif)</span>
            </Trans>
          }
        >
          {(a11y) => (
            <textarea
              {...a11y}
              name="intendedUse"
              maxLength={500}
              rows={3}
              placeholder={t`Ex. : interprétation de variants en oncogénétique`}
              className={`${inputClass} h-auto resize-y py-3`}
            />
          )}
        </Field>
        <Consent name="noPatientDataPledge" error={errors.noPatientDataPledge}>
          <Trans>Je m'engage à ne saisir aucune donnée permettant d'identifier un patient.</Trans>
        </Consent>
        <Consent name="termsAccepted" error={errors.termsAccepted}>
          <Trans>
            J'accepte les <a href="#" className="text-primary hover:underline">conditions d'utilisation</a> et la{' '}
            <a href="#" className="text-primary hover:underline">politique de confidentialité</a>.
          </Trans>
        </Consent>
        <Button type="submit" size="lg" className="h-[46px] text-[15px]" disabled={signUp.isPending}>
          {signUp.isPending ? <Trans>Envoi…</Trans> : <Trans>Envoyer ma demande</Trans>}
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          <Trans>
            Déjà un compte ?{' '}
            <LocalizedLink to="/sign-in" className="text-primary hover:underline">
              Se connecter
            </LocalizedLink>
          </Trans>
        </p>
      </form>
    </div>
  )
}

function Consent({ name, error, children }: { name: FieldName; error?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="flex items-start gap-2.5 text-[13px] leading-normal text-muted-foreground">
        <input
          type="checkbox"
          name={name}
          aria-invalid={Boolean(error)}
          className="mt-0.5 size-[18px] shrink-0 accent-primary"
        />
        <span>{children}</span>
      </label>
      {error && (
        <span role="alert" className="pl-7 text-xs text-destructive">
          {error}
        </span>
      )}
    </div>
  )
}
