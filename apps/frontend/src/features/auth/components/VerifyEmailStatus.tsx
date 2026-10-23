import { Trans, useLingui } from '@lingui/react/macro'
import { CircleCheck, CircleX, LoaderCircle } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { LocalizedLink } from '@/shared/components/LocalizedLink'
import { buttonVariants } from '@/shared/components/ui/button'
import { ApiError, errorMessage } from '@/shared/api/errors'
import { cn } from '@/lib/utils'
import { useVerifyEmail } from '../hooks'
import { ResendVerification } from './ResendVerification'

/**
 * Landing page of the link in the verification e-mail. The token is sent once on arrival: a link
 * only works once, so a second request (React strict mode, a reload) must not consume it again.
 */
export function VerifyEmailStatus({ token }: { token: string }) {
  const { i18n } = useLingui()
  const verify = useVerifyEmail()
  const sent = useRef(false)

  useEffect(() => {
    if (sent.current || !token) return
    sent.current = true
    verify.mutate(token)
  }, [token, verify])

  if (!token || verify.data?.ok === false) {
    const code = verify.data && !verify.data.ok ? verify.data.code : 'invalid_token'
    return (
      <div className="flex flex-col gap-6 animate-in fade-in" role="alert">
        <StatusIcon tone="error" />
        <div className="flex flex-col gap-2">
          <h1 className="text-[30px] font-semibold tracking-[-0.03em]">
            <Trans>Lien non valable</Trans>
          </h1>
          <p className="text-[15px] leading-relaxed text-muted-foreground">{i18n._(errorMessage(new ApiError(code, 422)))}</p>
        </div>
        <ResendVerification />
      </div>
    )
  }

  if (!verify.data) {
    return (
      <div className="flex items-center gap-3 text-muted-foreground" role="status">
        <LoaderCircle className="size-5 animate-spin" aria-hidden="true" />
        <Trans>Vérification de votre adresse…</Trans>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6 animate-in fade-in" role="status">
      <StatusIcon tone="success" />
      <div className="flex flex-col gap-2">
        <h1 className="text-[30px] font-semibold tracking-[-0.03em]">
          <Trans>Adresse confirmée</Trans>
        </h1>
        <p className="text-[15px] leading-relaxed text-muted-foreground">
          <Trans>Connectez-vous pour compléter votre profil : un administrateur examinera ensuite votre demande.</Trans>
        </p>
      </div>
      <LocalizedLink to="/sign-in" className={cn(buttonVariants({ size: 'lg' }), 'h-[50px] text-[15px]')}>
        <Trans>Se connecter</Trans>
      </LocalizedLink>
    </div>
  )
}

function StatusIcon({ tone }: { tone: 'success' | 'error' }) {
  const Icon = tone === 'success' ? CircleCheck : CircleX
  return (
    <span
      className={cn(
        'flex size-14 items-center justify-center rounded-2xl',
        tone === 'success' ? 'bg-success/14 text-success' : 'bg-destructive/10 text-destructive',
      )}
    >
      <Icon className="size-7" aria-hidden="true" />
    </span>
  )
}
