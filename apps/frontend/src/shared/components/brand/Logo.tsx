import { cn } from '@/lib/utils'
import { LogoMark } from './LogoMark'

type LogoProps = {
  /** Height of the mark in px; the wordmark is scaled from it. */
  size?: number
  className?: string
}

/** Wordmark source is 411×80 px. */
const WORDMARK_RATIO = 411 / 80

/**
 * Horizontal lockup: mark + wordmark from the official logo.
 * The wordmark has a light variant for dark mode; only the visible one is announced.
 */
export function Logo({ size = 32, className }: LogoProps) {
  const height = Math.round(size * 0.66)
  const width = Math.round(height * WORDMARK_RATIO)
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <LogoMark size={size} />
      <img src="/logo-wordmark.webp" width={width} height={height} alt="Genomica" className="dark:hidden" />
      <img src="/logo-wordmark-dark.webp" width={width} height={height} alt="Genomica" className="hidden dark:block" />
    </span>
  )
}
