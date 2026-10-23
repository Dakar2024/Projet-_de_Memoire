import { Trans, useLingui } from '@lingui/react/macro'
import { useNavigate, useParams } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'
import { Button } from '@/shared/components/ui/button'
import { PROFESSIONS } from '@/shared/api/contracts'
import { ApiError, errorMessage } from '@/shared/api/errors'
import { cn } from '@/lib/utils'
import { useCompleteOnboarding } from '../hooks'
import { PROFESSION_LABELS } from '../professions'
import { onboardingSchema } from '../schemas'
import { AuthHeading, Field, FormAlert, inputClass } from './FormBits'

type FieldName = 'fullName' | 'profession' | 'organization' | 'intendedUse'

/**
 * Profile asked once the e-mail is verified (MODELISATION_BACKEND.md § 4.1): the admin only reviews
 * complete requests. Unless the domain is open, the session ends here and the pending screen follows.
 */
export function OnboardingForm({ email }: { email: string }) {
  const { t, i18n } = useLingui()
  const navigate = useNavigate()
  const { lang } = useParams({ from: '/$lang' })
  const onboarding = useCompleteOnboarding()
  const [errors, setErrors] = useState<Partial<Record<FieldName, string>>>({})
  const [formError, setFormError] = useState<string | null>(null)

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    const form = new FormData(event.currentTarget)
    const parsed = onboardingSchema.safeParse({
      fullName: String(form.get('fullName') ?? ''),
      profession: String(form.get('profession') ?? ''),
      organization: String(form.get('organization') ?? ''),
      intendedUse: String(form.get('intendedUse') ?? ''),
    })
    if (!parsed.success) {
      const fields = new Set(parsed.error.issues.map((issue) => String(issue.path[0])))
      setErrors({
        fullName: fields.has('fullName') ? t`Indiquez votre nom.` : undefined,
        profession: fields.has('profession') ? t`Choisissez votre fonction.` : undefined,
        organization: fields.has('organization') ? t`Indiquez votre établissement.` : undefined,
        intendedUse: fields.has('intendedUse') ? t`2 000 caractères maximum.` : undefined,
      })
      return
    }
    setErrors({})
    onboarding.mutate(parsed.data, {
      onSuccess: (result) => {
        if (!result.ok) return setFormError(i18n._(errorMessage(new ApiError(result.code, 400))))
        if (result.user.status === 'active') return navigate({ to: '/$lang/assistant', params: { lang } })
        navigate({ to: '/$lang/pending', params: { lang }, search: { reason: 'pending_review' } })
      },
      onError: () => setFormError(i18n._(errorMessage(null))),
    })
  }

  return (
    <div className="flex flex-col gap-8 animate-in fade-in slide-in-from-bottom-1">
      <AuthHeading
        title={<Trans>Votre profil</Trans>}
        lead={<Trans>Dernière étape : ces informations permettent à un administrateur d'examiner votre demande.</Trans>}
      />
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-5">
        {formError && <FormAlert>{formError}</FormAlert>}
        <p className="-mb-1 text-sm text-muted-foreground">
          <Trans>
            Adresse confirmée : <span className="font-medium text-foreground">{email}</span>
          </Trans>
        </p>
        <Field label={<Trans>Nom complet</Trans>} error={errors.fullName}>
          {(a11y) => <input {...a11y} name="fullName" autoComplete="name" className={inputClass} />}
        </Field>
        <Field label={<Trans>Fonction</Trans>} error={errors.profession}>
          {(a11y) => (
            <select {...a11y} name="profession" defaultValue="" className={cn(inputClass, 'appearance-auto')}>
              <option value="" disabled>
                {t`Choisir…`}
              </option>
              {PROFESSIONS.map((id) => (
                <option key={id} value={id}>
                  {i18n._(PROFESSION_LABELS[id])}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={<Trans>Établissement ou laboratoire</Trans>} error={errors.organization}>
          {(a11y) => (
            <input
              {...a11y}
              name="organization"
              autoComplete="organization"
              placeholder={t`CHU, laboratoire, institut…`}
              className={inputClass}
            />
          )}
        </Field>
        <Field
          label={<Trans>Usage prévu</Trans>}
          error={errors.intendedUse}
          hint={<Trans>Facultatif. Par exemple : interprétation de variants BRCA en consultation d'oncogénétique.</Trans>}
        >
          {(a11y) => (
            <textarea
              {...a11y}
              name="intendedUse"
              rows={3}
              maxLength={2000}
              className={cn(inputClass, 'h-auto min-h-[96px] py-3')}
            />
          )}
        </Field>
        <Button type="submit" size="lg" className="h-[54px] w-full rounded-xl text-base font-semibold" disabled={onboarding.isPending}>
          {onboarding.isPending ? <Trans>Envoi…</Trans> : <Trans>Envoyer ma demande</Trans>}
        </Button>
      </form>
    </div>
  )
}
