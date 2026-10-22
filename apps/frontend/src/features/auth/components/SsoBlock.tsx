import { Trans, useLingui } from '@lingui/react/macro'
import { useState } from 'react'
import { buttonVariants } from '@/shared/components/ui/button'
import { cn } from '@/lib/utils'

const MICROSOFT_ENABLED = import.meta.env.VITE_AUTH_MICROSOFT === 'true'
const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

/**
 * Single sign-on above the e-mail form. Microsoft (Entra ID) rather than Google: hospitals mostly run
 * Microsoft 365, and a personal Google account would bypass the professional e-mail rule.
 * Hidden unless VITE_AUTH_MICROSOFT=true, so a dead button never ships; the backend route
 * /api/auth/microsoft/start does the OAuth dance and validates `next`.
 */
export function SsoBlock({ next }: { next?: string }) {
  const { t } = useLingui()
  const [notice, setNotice] = useState<string | null>(null)
  if (!MICROSOFT_ENABLED) return null

  const href = `/api/auth/microsoft/start${next ? `?next=${encodeURIComponent(next)}` : ''}`
  return (
    <div className="flex flex-col gap-4">
      <a
        href={href}
        onClick={(event) => {
          if (!USE_MOCKS) return
          event.preventDefault()
          setNotice(t`La connexion Microsoft sera disponible avec le backend. Utilisez votre e-mail en attendant.`)
        }}
        className={cn(buttonVariants({ variant: 'outline', size: 'lg' }), 'h-[54px] w-full rounded-xl text-[15px] font-semibold')}
      >
        <MicrosoftLogo />
        <Trans>Continuer avec Microsoft</Trans>
      </a>
      {notice && (
        <p role="status" className="rounded-2xl bg-muted p-4 text-sm leading-normal">
          {notice}
        </p>
      )}
      <div className="flex items-center gap-3 text-[13px] text-muted-foreground" aria-hidden="true">
        <span className="h-px flex-1 bg-border" />
        <Trans>ou avec votre e-mail professionnel</Trans>
        <span className="h-px flex-1 bg-border" />
      </div>
    </div>
  )
}

function MicrosoftLogo() {
  return (
    <svg viewBox="0 0 21 21" className="size-5" aria-hidden="true">
      <rect x="1" y="1" width="9" height="9" fill="#f25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
      <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
      <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
    </svg>
  )
}
