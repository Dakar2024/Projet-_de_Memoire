import { detectPreferredLocale, getLocaleFromPath } from '@/lib/i18n-utils'
import { redirect } from '@tanstack/react-router'
import { createMiddleware } from '@tanstack/react-start'


export const i18nMiddleware = createMiddleware().server(
  async ({ next, request }) => {
    const url = new URL(request.url)
    const pathname = url.pathname

    // Ignorer les fichiers statiques et assets
    if (
      pathname.startsWith('/assets') ||
      pathname.startsWith('/public') ||
      pathname.startsWith('/api') ||
      pathname.includes('.')
    ) {
      return next()
    }

    // Vérifier si la route a déjà un préfixe de langue
    const currentLocale = getLocaleFromPath(pathname)

    if (currentLocale) {

      // Route déjà préfixée, on continue
      // Note: On pourrait passer le locale dans le context si nécessaire
      return next()
    }

    // Route sans préfixe de langue, rediriger
    // Never log request headers here: the cookie header carries the session.
    const preferredLocale = detectPreferredLocale(request)


    // i18n.activate(preferredLocale) - Removed: activation should happen in the component tree

    // Check if we are at root, if so, redirect to preferred locale
    // If we are at /some-path, redirect to /en/some-path
    const newPathname = `/${preferredLocale}${pathname === '/' ? '' : pathname}`

    throw redirect({
      to: newPathname,
      search: url.search ? Object.fromEntries(url.searchParams) : undefined,
      hash: url.hash,
      statusCode: 307,
    })
  },
)
