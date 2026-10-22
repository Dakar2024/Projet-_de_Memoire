import { cn } from '@/lib/utils'

type LogoMarkProps = {
  /** Displayed size in px; the source image is 160 px, sharp up to ~53 px on 3x screens. */
  size?: number
  className?: string
}

/**
 * Genomica mark: the tile of the official logo (public/Genomica_logo.png), cut out with transparent
 * corners. Decorative where it sits next to the name, hence the empty alt.
 */
export function LogoMark({ size = 32, className }: LogoMarkProps) {
  return (
    <span className={cn('inline-flex shrink-0', className)} style={{ width: size, height: size }}>
      <img src="/logo-mark.webp" width={size} height={size} alt="" aria-hidden="true" decoding="async" />
    </span>
  )
}
