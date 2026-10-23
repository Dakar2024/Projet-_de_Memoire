import { Trans, useLingui } from '@lingui/react/macro'
import { useState, type FormEvent } from 'react'
import { Button, buttonVariants } from '@/shared/components/ui/button'
import { LocalizedLink } from '@/shared/components/LocalizedLink'
import { ApiError, errorMessage } from '@/shared/api/errors'
import { cn } from '@/lib/utils'
import { useResetPassword } from '../hooks'
import { PASSWORD_MIN_LENGTH, resetPasswordFormSchema } from '../schemas'
import { Field, FormAlert, PasswordInput, PasswordStrength } from './FormBits'

/** New password from the reset e-mail link; every other session is closed by the backend. */
export function ResetPasswordForm({ token }: { token: string }) {
  const { t, i18n } = useLingui()
  const reset = useResetPassword()
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<{ password?: string; passwordConfirm?: string }>({})
  const [formError, setFormError] = useState<string | null>(null)

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    const form = new FormData(event.currentTarget)
    const parsed = resetPasswordFormSchema.safeParse({
      token,
      password: String(form.get('password') ?? ''),
      passwordConfirm: String(form.get('passwordConfirm') ?? ''),
    })
    if (!parsed.success) {
      const fields = new Set(parsed.error.issues.map((issue) => String(issue.path[0])))
      if (fields.has('token')) return setFormError(i18n._(errorMessage(new ApiError('invalid_token', 422))))
      setErrors({
        password: fields.has('password') ? t`${PASSWORD_MIN_LENGTH} caractères minimum.` : undefined,
        passwordConfirm: fields.has('passwordConfirm') ? t`Les mots de passe ne correspondent pas.` : undefined,
      })
      return
    }
    setErrors({})
    reset.mutate(
      { token, password: parsed.data.password },
      {
        onSuccess: (result) => {
          if (!result.ok) setFormError(i18n._(errorMessage(new ApiError(result.code, 422))))
        },
        onError: () => setFormError(i18n._(errorMessage(null))),
      },
    )
  }

  if (reset.data?.ok) {
    return (
      <div className="flex flex-col gap-4 animate-in fade-in" role="status">
        <h1 className="text-[30px] font-semibold tracking-[-0.03em]">
          <Trans>Mot de passe modifié</Trans>
        </h1>
        <p className="text-[15px] leading-relaxed text-muted-foreground">
          <Trans>Vos autres sessions ont été fermées. Connectez-vous avec votre nouveau mot de passe.</Trans>
        </p>
        <LocalizedLink to="/sign-in" className={cn(buttonVariants({ size: 'lg' }), 'h-[50px] text-[15px]')}>
          <Trans>Se connecter</Trans>
        </LocalizedLink>
      </div>
    )
  }

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-[18px]">
      <div className="flex flex-col gap-2">
        <h1 className="text-[30px] font-semibold tracking-[-0.03em]">
          <Trans>Nouveau mot de passe</Trans>
        </h1>
        <p className="text-[15px] text-muted-foreground">
          <Trans>Choisissez un mot de passe que vous n'utilisez pas ailleurs.</Trans>
        </p>
      </div>
      {formError && (
        <FormAlert>
          {formError}{' '}
          <LocalizedLink to="/forgot-password" className="font-semibold underline underline-offset-4">
            <Trans>Demander un nouveau lien</Trans>
          </LocalizedLink>
        </FormAlert>
      )}
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
      <Button type="submit" size="lg" className="h-[50px] text-[15px]" disabled={reset.isPending}>
        {reset.isPending ? <Trans>Enregistrement…</Trans> : <Trans>Enregistrer</Trans>}
      </Button>
    </form>
  )
}
