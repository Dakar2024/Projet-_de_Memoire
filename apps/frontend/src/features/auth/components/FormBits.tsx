import { Trans, useLingui } from '@lingui/react/macro'
import { Eye, EyeOff } from 'lucide-react'
import { useId, useState, type ComponentProps, type ReactNode } from 'react'
import { Label } from '@/shared/components/ui/label'
import { LocalizedLink } from '@/shared/components/LocalizedLink'
import { cn } from '@/lib/utils'
import { passwordStrength } from '../schemas'

export const inputClass =
  'h-[52px] w-full rounded-xl border border-border bg-card px-4 text-[15px] text-foreground transition-[border-color,box-shadow] placeholder:text-faint hover:border-primary/40 focus:border-primary focus:shadow-[0_0_0_4px_color-mix(in_oklab,var(--primary)_18%,transparent)] focus:outline-none aria-[invalid=true]:border-destructive'

/** Pill-shaped switch between the two forms; each side is its own route, so the URL says which form is shown. */
export function AuthTabs({ current }: { current: 'sign-in' | 'sign-up' }) {
  const { t } = useLingui()
  const item = (active: boolean) =>
    cn(
      'relative inline-flex min-h-10 items-center rounded-full px-[18px] text-sm font-semibold transition-colors duration-200',
      active ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
    )
  return (
    <nav aria-label={t`Connexion ou inscription`} className="inline-flex gap-1 self-start rounded-full bg-muted p-1">
      <LocalizedLink to="/sign-in" className={item(current === 'sign-in')} aria-current={current === 'sign-in' ? 'page' : undefined}>
        <Trans>Connexion</Trans>
      </LocalizedLink>
      <LocalizedLink to="/sign-up" className={item(current === 'sign-up')} aria-current={current === 'sign-up' ? 'page' : undefined}>
        <Trans>Inscription</Trans>
      </LocalizedLink>
    </nav>
  )
}

/** Big heading + one-line lead, shared by both forms. */
export function AuthHeading({ title, lead }: { title: ReactNode; lead: ReactNode }) {
  return (
    <div className="flex flex-col gap-2.5">
      <h1 className="text-[clamp(36px,4.2vw,48px)] font-bold leading-none tracking-[-0.035em]">{title}</h1>
      <p className="text-base text-muted-foreground">{lead}</p>
    </div>
  )
}

type FieldProps = {
  label: ReactNode
  error?: string
  hint?: ReactNode
  aside?: ReactNode
  children: (props: { id: string; 'aria-invalid': boolean; 'aria-describedby'?: string }) => ReactNode
}

/** Label, control, then either the error (announced) or the hint, linked through aria-describedby. */
export function Field({ label, error, hint, aside, children }: FieldProps) {
  const id = useId()
  const noteId = `${id}-note`
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <Label htmlFor={id} className="text-sm font-medium">
          {label}
        </Label>
        {aside}
      </div>
      {children({ id, 'aria-invalid': Boolean(error), 'aria-describedby': error || hint ? noteId : undefined })}
      {error ? (
        <span id={noteId} role="alert" className="text-xs text-destructive">
          {error}
        </span>
      ) : hint ? (
        <span id={noteId} className="text-xs text-faint">
          {hint}
        </span>
      ) : null}
    </div>
  )
}

export function PasswordInput(props: ComponentProps<'input'>) {
  const { t } = useLingui()
  const [visible, setVisible] = useState(false)
  return (
    <div className="relative">
      <input {...props} type={visible ? 'text' : 'password'} className={cn(inputClass, 'pr-12')} />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        className="absolute right-1 top-1/2 flex size-11 -translate-y-1/2 items-center justify-center text-muted-foreground hover:text-foreground"
        aria-label={visible ? t`Masquer le mot de passe` : t`Afficher le mot de passe`}
        aria-pressed={visible}
      >
        {visible ? <EyeOff className="size-[18px]" /> : <Eye className="size-[18px]" />}
      </button>
    </div>
  )
}

const METER_COLORS = ['var(--destructive)', '#e07b39', '#c9a227', 'var(--success)']

export function PasswordStrength({ password }: { password: string }) {
  const { t } = useLingui()
  const score = passwordStrength(password)
  const labels = [
    t`12 caractères minimum, avec majuscules, chiffres et symboles.`,
    t`Trop faible`,
    t`Moyen`,
    t`Bon`,
    t`Excellent`,
  ]
  return (
    <div className="flex flex-col gap-1.5">
      <div className="grid grid-cols-4 gap-1" aria-hidden="true">
        {[1, 2, 3, 4].map((n) => (
          <span
            key={n}
            className="h-1 rounded-sm bg-border transition-colors"
            style={score >= n ? { background: METER_COLORS[score - 1] } : undefined}
          />
        ))}
      </div>
      <span className="text-xs text-muted-foreground" aria-live="polite">
        {labels[score]}
      </span>
    </div>
  )
}

export function FormAlert({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/8 px-4 py-3 text-sm text-destructive">
      {children}
    </div>
  )
}
