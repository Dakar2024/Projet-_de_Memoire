import { useLingui } from '@lingui/react/macro'
import { Moon, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'
import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

/** Light/dark toggle; « système » stays the default until the user picks one (Préférences offers all three). */
export function ThemeToggle({ className }: { className?: string }) {
  const { t } = useLingui()
  const { resolvedTheme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)

  // The resolved theme is only known in the browser: render a neutral box until hydration.
  useEffect(() => setMounted(true), [])

  const isDark = mounted && resolvedTheme === 'dark'
  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      className={cn(
        'inline-flex size-11 items-center justify-center rounded-[10px] border border-border text-foreground transition-colors hover:bg-muted',
        className,
      )}
      aria-label={isDark ? t`Passer au thème clair` : t`Passer au thème sombre`}
    >
      {mounted && (isDark ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />)}
    </button>
  )
}
