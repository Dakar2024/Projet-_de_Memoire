import {
  HeadContent,
  Scripts,
  createRootRouteWithContext,
  useLocation,
} from '@tanstack/react-router'
import { TanStackRouterDevtoolsPanel } from '@tanstack/react-router-devtools'
import { TanStackDevtools } from '@tanstack/react-devtools'

import { setupI18n } from '@lingui/core'
import { I18nProvider } from '@lingui/react'
import { messages as enMessages } from '../locales/en/messages'
import { messages as frMessages } from '../locales/fr/messages'
import { useMemo } from 'react'

import TanStackQueryDevtools from '../shared/providers/tanstack-query/devtools'

import appCss from '../styles.css?url'

import { queryOptions, type QueryClient } from '@tanstack/react-query'
import { i18nMiddleware } from '@/middlewares/i18n'
import { ToasterProvider } from '@/shared/providers/toaster-provider'
import { DEFAULT_LOCALE, getLocaleFromPath } from '@/lib/i18n-utils'
import { ThemeProvider } from 'next-themes'
import { TooltipProvider } from '@/shared/components/ui/tooltip'
import { getAccentFn } from '@/features/preferences/accent'

interface MyRouterContext {
  queryClient: QueryClient
}

const ALL_MESSAGES = {
  en: enMessages,
  fr: frMessages,
}

export const accentQuery = queryOptions({
  queryKey: ['preferences', 'accent'],
  queryFn: () => getAccentFn(),
  staleTime: Infinity,
})

export const Route = createRootRouteWithContext<MyRouterContext>()({
  beforeLoad: async ({ context }) => ({
    accent: await context.queryClient.ensureQueryData(accentQuery),
  }),
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { title: 'Genomica — les variants de l’ADN, expliqués avec leurs sources' },
      {
        name: 'description',
        content:
          'Interrogez ClinVar, MedGen, HPO et NCBI Gene en langage naturel : réponses sourcées sur les variants d’intérêt clinique.',
      },
      { property: 'og:title', content: 'Genomica' },
      {
        property: 'og:description',
        content: 'Les variants de l’ADN, expliqués avec leurs sources.',
      },
      { property: 'og:type', content: 'website' },
      { name: 'theme-color', content: '#0f766e' },
    ],
    links: [
      { rel: 'stylesheet', href: appCss },
      { rel: 'icon', href: '/favicon-32.png', type: 'image/png', sizes: '32x32' },
      { rel: 'apple-touch-icon', href: '/apple-touch-icon.png' },
      { rel: 'manifest', href: '/manifest.json' },
    ],
  }),
  server: {
    middleware: [i18nMiddleware],
  },
  shellComponent: RootDocument,
})

function RootDocument({ children }: { children: React.ReactNode }) {
  const pathname = useLocation({
    select: (location) => location.pathname,
  })
  const { accent } = Route.useRouteContext()

  const locale = getLocaleFromPath(pathname) || DEFAULT_LOCALE

  // Create an i18n instance for *this* render.
  // This avoids calling i18n.activate() during render (which triggers updates in <I18nProvider />).
  const i18n = useMemo(() => {
    return setupI18n({
      locale,
      messages: ALL_MESSAGES,
    })
  }, [locale])

  return (
    <html lang={locale} data-accent={accent} suppressHydrationWarning>
      <head>
        <HeadContent />
      </head>
      <body>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <I18nProvider i18n={i18n}>
            <TooltipProvider delayDuration={300}>
              {children}
              <ToasterProvider />
            </TooltipProvider>
            {import.meta.env.DEV && (
              <TanStackDevtools
                config={{
                  position: 'bottom-right',
                }}
                plugins={[
                  {
                    name: 'Tanstack Router',
                    render: <TanStackRouterDevtoolsPanel />,
                  },
                  TanStackQueryDevtools,
                ]}
              />
            )}
            <Scripts />
          </I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
