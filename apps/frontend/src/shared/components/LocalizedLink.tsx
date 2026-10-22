import { useLocale } from '@/lib/i18n-utils'
import { Link, type LinkProps } from '@tanstack/react-router'
import { FileRoutesByTo } from '../../routeTree.gen'

type StripLang<T extends string> = T extends `/$lang${infer R}`
  ? R extends ''
  ? '/'
  : R
  : T

type LocalizedLinkProps = Omit<LinkProps, 'to'> & {
  to: StripLang<keyof FileRoutesByTo & string>
  className?: string
  children?: React.ReactNode
}

/**
 * Component Link that automatically adds the language prefix
 * Supports autocompletion for routes by stripping '/$lang' from the keys
 */
export function LocalizedLink({ to, ...props }: LocalizedLinkProps) {
  const locale = useLocale()

  // Reconstruct the full path
  // If to is '/', we want '/$lang' (which is just /$lang in the route tree)
  // When we have '/about', we want '/fr/about'

  const targetPath = to === '/' ? '' : to
  const localizedTo = `/${locale}${targetPath}`

  return <Link to={localizedTo as any} {...props} />
}